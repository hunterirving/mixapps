#!/usr/bin/env python3
"""
Starts HTTP server for local testing
Automatically manages a virtual environment for dependencies
"""

import http.server
import socketserver
import socket
import sys
import os
import json
import queue
import threading
import subprocess
import time
import urllib.parse
from pathlib import Path

DEFAULT_PORT = 8000
SCRIPT_DIR = Path(__file__).parent.absolute()
VENV_DIR = SCRIPT_DIR / "venv"
MIX_DIR = SCRIPT_DIR / "mix"
TRACKS_PATH = MIX_DIR / "tracks.json"

# Serializes all reads/writes of tracks.json so rescans, reorders, and future
# uploads can't race each other.
tracks_lock = threading.Lock()

# Set of per-client SSE queues. Each connected /events client gets a queue;
# broadcast_tracks() pushes the latest tracks list onto every queue.
sse_subscribers = set()
sse_subscribers_lock = threading.Lock()

# Canonical serialization of the most recently broadcast tracks list, so we
# can fire on any content change (file add/remove/reorder or a hand-edit to
# tracks.json's metadata) instead of only when /mix's filenames change.
last_broadcast_serialized = None


def run_in_venv():
	"""Re-run this script in the shared venv with serve.py's deps available"""
	import scan
	python_path = scan.setup_venv(packages=("qrcode", "mutagen"))
	try:
		subprocess.check_call([str(python_path), __file__, "--in-venv"])
	except (KeyboardInterrupt, subprocess.CalledProcessError):
		pass
	sys.exit(0)


def get_local_ip():
	"""Get the local IP address for network access"""
	try:
		# Create a socket to determine the local IP
		s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		# Connect to a public DNS server (doesn't actually send data)
		s.connect(("8.8.8.8", 80))
		local_ip = s.getsockname()[0]
		s.close()
		return local_ip
	except Exception:
		return "Unable to determine"


def find_available_port(start_port=DEFAULT_PORT, max_attempts=10):
	"""Find an available port starting from start_port"""
	for port in range(start_port, start_port + max_attempts):
		try:
			with socketserver.TCPServer(("", port), None) as s:
				return port
		except OSError:
			continue
	return None


def print_qr_code(url):
	"""Generate and print a QR code using block characters"""
	try:
		import qrcode

		qr = qrcode.QRCode(
			version=1,
			error_correction=qrcode.constants.ERROR_CORRECT_L,
			box_size=1,
			border=1,
		)
		qr.add_data(url)
		qr.make(fit=True)

		# Get the QR code matrix
		matrix = qr.get_matrix()

		print("\nScan to connect:")
		for y in range(0, len(matrix), 2):
			line = ""
			for x in range(len(matrix[y])):
				top = matrix[y][x]
				bottom = matrix[y + 1][x] if y + 1 < len(matrix) else False
				if top and bottom:
					line += "█"
				elif top:
					line += "▀"
				elif bottom:
					line += "▄"
				else:
					line += " "
			print(line)
		print()
	except ImportError:
		print("\nQR code generation unavailable (qrcode library not installed)")
	except Exception as e:
		print(f"\nCould not generate QR code: {e}")


def read_tracks():
	"""Read tracks.json from disk; return [] if missing or malformed."""
	if not TRACKS_PATH.exists():
		return []
	try:
		with open(TRACKS_PATH, 'r', encoding='utf-8') as f:
			loaded = json.load(f)
		return loaded if isinstance(loaded, list) else []
	except (json.JSONDecodeError, OSError):
		return []


def broadcast_tracks(tracks, renames=None):
	"""Push the current tracks list to every connected SSE client if its
	content differs from the last broadcast. `renames`, when non-empty,
	carries [{from, to}, ...] so clients can migrate per-track state (eg.
	preloaded blob URLs) without losing it across a canonicalizing rename.
	Caller must hold tracks_lock."""
	global last_broadcast_serialized
	serialized = json.dumps(tracks, ensure_ascii=False, sort_keys=True)
	if serialized == last_broadcast_serialized and not renames:
		return
	last_broadcast_serialized = serialized
	payload = {'tracks': tracks, 'renames': renames or []}
	with sse_subscribers_lock:
		subscribers = list(sse_subscribers)
	for q in subscribers:
		try:
			q.put_nowait(payload)
		except queue.Full:
			pass


def rescan_and_maybe_broadcast():
	"""Rescan /mix, then broadcast if the resulting tracks list differs from
	what we last sent."""
	import scan
	tracks, _changed, renames = scan.rescan(silent=True)
	broadcast_tracks(tracks, renames=renames)
	return tracks


def start_rescan_ticker(interval=1.0):
	"""Background thread that periodically rescans /mix so changes made
	directly on disk (eg. user dragging a file in or `rm`-ing one from the
	terminal) reach connected clients without anyone hitting the server."""
	def tick():
		while True:
			time.sleep(interval)
			try:
				with tracks_lock:
					rescan_and_maybe_broadcast()
			except Exception as e:
				# Don't let a bad scan kill the ticker.
				print(f"rescan tick error: {e}", file=sys.stderr)
	t = threading.Thread(target=tick, daemon=True)
	t.start()


def start_server():
	"""Start the HTTP server (runs after venv is set up)"""
	# Change to script directory
	os.chdir(SCRIPT_DIR)

	# Periodically rescan /mix so on-disk changes propagate to the UI even
	# when nothing is hitting an HTTP endpoint.
	start_rescan_ticker()

	# Find an available port
	port = find_available_port(DEFAULT_PORT)

	if port is None:
		print(f"Error: Could not find an available port (tried {DEFAULT_PORT}-{DEFAULT_PORT + 9})")
		sys.exit(1)

	# Get local IP for network access
	local_ip = get_local_ip()

	# Create server
	Handler = http.server.SimpleHTTPRequestHandler

	# Suppress default logging and broken pipe errors
	class QuietHandler(Handler):
		def end_headers(self):
			self.send_header('Cache-Control', 'no-cache')
			super().end_headers()

		def log_message(self, format, *args):
			pass

		def handle(self):
			"""Handle requests and suppress broken pipe errors"""
			try:
				super().handle()
			except (BrokenPipeError, ConnectionResetError):
				# Browser cancelled the request (normal for media streaming/preloading)
				pass

		def do_GET(self):
			# Rescan /mix on every tracks.json fetch so the page always sees
			# what's actually on disk (added via rip.py/buy.py or by hand).
			if self.path == '/mix/tracks.json':
				with tracks_lock:
					rescan_and_maybe_broadcast()
				return super().do_GET()

			if self.path == '/events':
				return self._serve_sse()

			return super().do_GET()

		def _serve_sse(self):
			"""Server-Sent Events stream of tracks.json changes."""
			self.send_response(200)
			self.send_header('Content-Type', 'text/event-stream')
			self.send_header('Cache-Control', 'no-cache')
			self.send_header('Connection', 'keep-alive')
			self.send_header('X-Accel-Buffering', 'no')
			self.end_headers()

			q = queue.Queue(maxsize=16)
			with sse_subscribers_lock:
				sse_subscribers.add(q)

			try:
				# Initial sync so a fresh tab gets the current state without
				# waiting for the next change. No renames context: a fresh
				# client has no prior state to migrate from.
				with tracks_lock:
					initial = read_tracks()
				self._send_sse_event('tracks', {'tracks': initial, 'renames': []})

				while True:
					try:
						payload = q.get(timeout=15)
						self._send_sse_event('tracks', payload)
					except queue.Empty:
						# Heartbeat keeps proxies and idle connections from
						# closing the stream.
						self.wfile.write(b': keepalive\n\n')
						self.wfile.flush()
			except (BrokenPipeError, ConnectionResetError, OSError):
				pass
			finally:
				with sse_subscribers_lock:
					sse_subscribers.discard(q)

		def _send_sse_event(self, event, data):
			payload = json.dumps(data, ensure_ascii=False)
			message = f'event: {event}\ndata: {payload}\n\n'.encode('utf-8')
			self.wfile.write(message)
			self.wfile.flush()

		def do_POST(self):
			# Local-only: receive a reordered tracks array and overwrite tracks.json
			if self.path != '/tracks':
				self.send_response(404)
				self.end_headers()
				return
			length = int(self.headers.get('Content-Length', '0'))
			payload = json.loads(self.rfile.read(length))
			with tracks_lock:
				TRACKS_PATH.write_text(
					json.dumps(payload, indent='\t', ensure_ascii=False) + '\n',
					encoding='utf-8',
				)
				broadcast_tracks(payload)
			self.send_response(204)
			self.end_headers()

		def do_DELETE(self):
			# Local-only: remove a track's audio file from /mix and prune
			# tracks.json. Path is /tracks/<url-encoded-filename>.
			prefix = '/tracks/'
			if not self.path.startswith(prefix):
				self.send_response(404)
				self.end_headers()
				return

			filename = urllib.parse.unquote(self.path[len(prefix):])
			target = (MIX_DIR / filename).resolve()
			try:
				target.relative_to(MIX_DIR.resolve())
			except ValueError:
				self.send_response(400)
				self.end_headers()
				return
			if target == TRACKS_PATH.resolve() or target.name != filename:
				self.send_response(400)
				self.end_headers()
				return
			with tracks_lock:
				try:
					target.unlink()
				except FileNotFoundError:
					pass
				except OSError as e:
					self.send_response(500)
					self.end_headers()
					self.wfile.write(str(e).encode('utf-8'))
					return
				tracks = [t for t in read_tracks() if t.get('filename') != filename]
				TRACKS_PATH.write_text(
					json.dumps(tracks, indent='\t', ensure_ascii=False) + '\n',
					encoding='utf-8',
				)
				broadcast_tracks(tracks)
			self.send_response(204)
			self.end_headers()

	try:
		with socketserver.ThreadingTCPServer(("", port), QuietHandler) as httpd:
			httpd.daemon_threads = True
			local_url = f"http://localhost:{port}"
			network_url = f"http://{local_ip}:{port}"

			print("=" * 60)
			print("💿 mixapps")
			print("=" * 60)
			print(f"\nServer running on port {port}")

			# Print QR code for easy mobile access
			print_qr_code(network_url)

			print(f"Local access:   {local_url}")
			print(f"Network access: {network_url}")
			print("\nPress Ctrl+C to stop the server")

			# Serve forever
			httpd.serve_forever()

	except KeyboardInterrupt:
		print("\n\nShutting down server...")
		sys.exit(0)
	except Exception as e:
		print(f"\nError starting server: {e}")
		sys.exit(1)


def main():
	"""Main entry point"""
	# Check if we're already running in venv
	if "--in-venv" not in sys.argv:
		run_in_venv()
	else:
		start_server()


if __name__ == "__main__":
	main()
