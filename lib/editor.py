"""
Handles track edits (reorder, upload, delete) from the browser.
Sends track list changes to open browser tabs as they happen.
Rebuilds manifest.json and service-worker.js when /mix changes.
serve.py uses this to serve your mixapp.
"""

import http.server
import sys
import json
import queue
import threading
import time
import urllib.parse
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent.absolute()
MIX_DIR = ROOT_DIR / "mix"
TRACKS_PATH = MIX_DIR / "tracks.json"

PUBLIC_FILES = {"index.html", "manifest.json", "service-worker.js"}
PUBLIC_DIRS = {"resources", "mix"}

SUPPORTED_UPLOAD_EXTENSIONS = ('.mp3', '.m4a', '.ogg', '.flac', '.wav')
MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # 200 MB per request

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


def _move_track_to(tracks, filename, insert_after):
	"""Reorder `tracks` in place so the entry matching `filename` lands at
	insert_after + 1 (clamped). Persists tracks.json if the order actually
	changed. Returns True iff a move happened. Caller must hold tracks_lock."""
	cur_idx = next((i for i, t in enumerate(tracks) if t.get('filename') == filename), -1)
	if cur_idx == -1:
		return False
	target_idx = max(0, min(insert_after + 1, len(tracks) - 1))
	if target_idx == cur_idx:
		return False
	entry = tracks.pop(cur_idx)
	if target_idx > cur_idx:
		target_idx -= 1
	tracks.insert(target_idx, entry)
	TRACKS_PATH.write_text(
		json.dumps(tracks, indent='\t', ensure_ascii=False) + '\n',
		encoding='utf-8',
	)
	return True


def _canonical_name_for(audio_path, fallback_name):
	"""Return the 'Artist – Title.ext' filename scan would canonicalize this
	upload to, so we can dedup BEFORE moving the file into /mix. Returns None
	if metadata can't be read."""
	import scan
	try:
		from mutagen import File as MutagenFile  # type: ignore
	except ImportError:
		return None
	try:
		audio = MutagenFile(audio_path, easy=True)
	except Exception:
		return None
	title = None
	artist = None
	if audio and audio.tags:
		title = audio.tags.get('title', [None])[0]
		artist = audio.tags.get('artist', [None])[0]
	if not title:
		title = Path(fallback_name).stem
	if not artist:
		artist = "Unknown Artist"
	ext = Path(fallback_name).suffix
	return f"{scan._sanitize_filename(artist)} – {scan._sanitize_filename(title)}{ext}"


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


# Snapshot of the files the PWA build reads, as of the last build.
last_pwa_signature = None


def rebuild_pwa_if_changed():
	"""Regenerate manifest.json and service-worker.js when any file they're
	built from has changed. Returns the mix name after a rebuild, else None."""
	global last_pwa_signature
	import build
	inputs = [*MIX_DIR.iterdir(), ROOT_DIR / "resources" / "styles.css"]
	signature = sorted((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in inputs if p.exists())
	if signature == last_pwa_signature:
		return None
	last_pwa_signature = signature
	return build.build_pwa(silent=True)


def print_mix_name(name):
	import build
	print(f"Mix name:       {name}")
	if name == build.DEFAULT_NAME:
		print("                (put a name in mix/name.txt to change it)")


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
					rebuild_pwa_if_changed()
			except Exception as e:
				# Don't let a bad scan kill the ticker.
				print(f"rescan tick error: {e}", file=sys.stderr)
	t = threading.Thread(target=tick, daemon=True)
	t.start()


class TrackRequestHandler(http.server.SimpleHTTPRequestHandler):
	# keep-alive; every response below needs a Content-Length or must close
	protocol_version = 'HTTP/1.1'
	# don't let idle connections pin threads forever
	timeout = 60
	# Nagle would stall the body write behind the header write
	disable_nagle_algorithm = True

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

	def _is_public(self, fs_path):
		parts = Path(fs_path).relative_to(self.directory).parts
		if not parts:
			return True
		if any(part.startswith('.') for part in parts):
			return False
		if len(parts) == 1:
			return parts[0] in PUBLIC_FILES
		name = parts[-1].lower()
		return parts[0] in PUBLIC_DIRS and name != 'readme.md' and not name.endswith('.uploading')

	def send_head(self):
		if not self._is_public(self.translate_path(self.path)):
			self.send_error(404)
			return None
		return super().send_head()

	def list_directory(self, path):
		self.send_error(404)
		return None

	def _serve_sse(self):
		"""Server-Sent Events stream of tracks.json changes."""
		self.send_response(200)
		self.send_header('Content-Type', 'text/event-stream')
		self.send_header('Cache-Control', 'no-cache')
		# The stream has no Content-Length, so under HTTP/1.1 it has to be
		# delimited by closing the socket. Sending this also flips
		# close_connection, so the handler won't try to reuse the socket.
		self.send_header('Connection', 'close')
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

	def _reply_status(self, status, body=b''):
		"""Short reply with a Content-Length. Errors also close the socket,
		since an early return can leave an unread body in the buffer."""
		if isinstance(body, str):
			body = body.encode('utf-8')
		self.send_response(status)
		self.send_header('Content-Length', str(len(body)))
		if status >= 400:
			self.send_header('Connection', 'close')
		self.end_headers()
		if body:
			try:
				self.wfile.write(body)
			except (BrokenPipeError, ConnectionResetError):
				pass

	def _reply_json(self, status, payload):
		body = json.dumps(payload).encode('utf-8')
		self.send_response(status)
		self.send_header('Content-Type', 'application/json')
		self.send_header('Content-Length', str(len(body)))
		self.end_headers()
		self.wfile.write(body)

	def _send_sse_event(self, event, data):
		payload = json.dumps(data, ensure_ascii=False)
		message = f'event: {event}\ndata: {payload}\n\n'.encode('utf-8')
		self.wfile.write(message)
		self.wfile.flush()

	def do_POST(self):
		# Local-only: receive a reordered tracks array and overwrite tracks.json
		if self.path != '/tracks':
			self._reply_status(404)
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

	def do_PUT(self):
		# Local-only: drag-and-drop upload from a connected browser.
		# Path is /upload/<url-encoded-filename>; headers carry the
		# desired insertion index (X-Insert-After: -1 means prepend).
		prefix = '/upload/'
		if not self.path.startswith(prefix):
			self._reply_status(404)
			return

		raw_name = urllib.parse.unquote(self.path[len(prefix):])
		# Strip any client-supplied path components.
		filename = Path(raw_name).name
		ext = Path(filename).suffix.lower()
		if not filename or ext not in SUPPORTED_UPLOAD_EXTENSIONS:
			self._reply_status(415)
			return

		length = int(self.headers.get('Content-Length', '0'))
		if length <= 0 or length > MAX_UPLOAD_BYTES:
			self._reply_status(413)
			return

		try:
			insert_after = int(self.headers.get('X-Insert-After', '-1'))
		except ValueError:
			insert_after = -1

		# Stream the body to a temp file in MIX_DIR, then move into place
		# atomically so a partial write is never visible to the rescan.
		MIX_DIR.mkdir(parents=True, exist_ok=True)
		tmp_path = MIX_DIR / (filename + '.uploading')
		try:
			with open(tmp_path, 'wb') as out:
				remaining = length
				while remaining > 0:
					chunk = self.rfile.read(min(64 * 1024, remaining))
					if not chunk:
						break
					out.write(chunk)
					remaining -= len(chunk)
			if remaining != 0:
				tmp_path.unlink(missing_ok=True)
				self._reply_status(400)
				return

			with tracks_lock:
				import scan
				# Dedup by canonical name: if a file with the canonical
				# "Artist – Title.ext" name already lives in /mix, drop
				# the upload and just reorder the existing entry to the
				# requested slot so the client still gets the FLIP.
				canonical = _canonical_name_for(tmp_path, filename)
				if canonical and (MIX_DIR / canonical).exists():
					tmp_path.unlink(missing_ok=True)
					tracks = read_tracks()
					moved = _move_track_to(tracks, canonical, insert_after)
					if moved:
						broadcast_tracks(tracks)
					final_index = next((i for i, t in enumerate(tracks) if t.get('filename') == canonical), -1)
					self._reply_json(200, {'filename': canonical, 'duplicate': True, 'moved': moved, 'final_index': final_index})
					return

				tmp_path.rename(MIX_DIR / filename)
				placed_name = filename

				tracks, _changed, renames = scan.rescan(silent=True)

				# Find the canonical (post-canonicalize) filename for the
				# upload by following the rename chain.
				new_name = placed_name
				for r in renames:
					if r['from'] == new_name:
						new_name = r['to']

				_move_track_to(tracks, new_name, insert_after)
				broadcast_tracks(tracks, renames=renames)
				final_index = next((i for i, t in enumerate(tracks) if t.get('filename') == new_name), -1)

			self._reply_json(200, {'filename': new_name, 'final_index': final_index})
		except Exception as e:
			tmp_path.unlink(missing_ok=True)
			self._reply_status(500, str(e))

	def do_DELETE(self):
		# Local-only: remove a track's audio file from /mix and prune
		# tracks.json. Path is /tracks/<url-encoded-filename>.
		prefix = '/tracks/'
		if not self.path.startswith(prefix):
			self._reply_status(404)
			return

		filename = urllib.parse.unquote(self.path[len(prefix):])
		target = (MIX_DIR / filename).resolve()
		try:
			target.relative_to(MIX_DIR.resolve())
		except ValueError:
			self._reply_status(400)
			return
		if target == TRACKS_PATH.resolve() or target.name != filename:
			self._reply_status(400)
			return
		with tracks_lock:
			try:
				target.unlink()
			except FileNotFoundError:
				pass
			except OSError as e:
				self._reply_status(500, str(e))
				return
			tracks = [t for t in read_tracks() if t.get('filename') != filename]
			TRACKS_PATH.write_text(
				json.dumps(tracks, indent='\t', ensure_ascii=False) + '\n',
				encoding='utf-8',
			)
			broadcast_tracks(tracks)
		self.send_response(204)
		self.end_headers()
