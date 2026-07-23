#!/usr/bin/env python3
"""
Serve a mixapp over HTTPS on your local network so you can install it as a PWA
without a public web host or tunnel.

Uses mkcert to mint a locally-trusted certificate for this machine's LAN IP. A
device won't trust that cert until it trusts mkcert's root CA, so we print
two QR codes:

	1. an HTTP link that hands the device the mkcert root CA (the public root
	   cert, no secret; served to any device until you stop the script)
	2. an HTTPS link to the mixapp itself, for PWA installation

Both servers shut down together on Ctrl+C.

After scanning the first QR code, install + trust the CA on the device:
	iOS:     Settings → General → VPN & Device Management → install the profile,
	         then Settings → General → About → Certificate Trust Settings →
	         enable full trust
	Android: open the downloaded file and follow the prompt to install it as a
	         CA certificate

Run with --reset to revoke the CA and delete the local certificates.
"""

import http.server
import socketserver
import socket
import ssl
import sys
import os
import json
import subprocess
import threading
from pathlib import Path

import serve  # reuse serve.py's track-management backend (TrackRequestHandler, SSE, etc.)

CERT_HTTP_PORT = 8001  # preferred; falls back to the next free port
HTTPS_PORT = 8443      # preferred; falls back to the next free port
SCRIPT_DIR = Path(__file__).parent.absolute()
CERT_DIR = SCRIPT_DIR / ".https_certs"
CERT_FILE = CERT_DIR / "cert.pem"
KEY_FILE = CERT_DIR / "key.pem"
MANIFEST_FILE = SCRIPT_DIR / "manifest.json"

# Path the phone fetches the root CA from. Anything else over HTTP 404s.
CA_DOWNLOAD_PATH = "/rootCA.pem"


def manifest_base_path():
	"""The base path the PWA was built for (manifest scope/start_url).
	The installed app launches here, so we must serve the project under
	it or the standalone window 404s. Defaults to '/'."""
	try:
		manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
	except (OSError, json.JSONDecodeError):
		return "/"
	base = manifest.get("scope") or manifest.get("start_url") or "/"
	if not base.startswith("/"):
		base = "/" + base
	if not base.endswith("/"):
		base = base + "/"
	return base


def run_in_venv():
	"""Re-run this script in the shared venv with qrcode available,
	forwarding any user flags (eg. --reset) to the re-exec."""
	import scan
	# mutagen: serve.py's upload path reads tags to canonicalize filenames.
	python_path = scan.setup_venv(packages=("qrcode", "mutagen"))
	try:
		subprocess.check_call([str(python_path), __file__, "--in-venv", *sys.argv[1:]])
	except (KeyboardInterrupt, subprocess.CalledProcessError):
		pass
	sys.exit(0)


def get_local_ip():
	"""Get the LAN IP other devices on the network can reach this machine at."""
	try:
		s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		s.connect(("8.8.8.8", 80))
		local_ip = s.getsockname()[0]
		s.close()
		return local_ip
	except Exception:
		return None


def find_available_port(start_port, max_attempts=20):
	"""Return the first bindable port at or after start_port. Uses SO_REUSEADDR
	so a socket lingering in TIME_WAIT from a prior run doesn't block us."""
	for port in range(start_port, start_port + max_attempts):
		s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
		try:
			s.bind(("", port))
			return port
		except OSError:
			continue
		finally:
			s.close()
	return None


def print_qr_code(url, caption):
	"""Generate and print a QR code using block characters."""
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

		matrix = qr.get_matrix()

		print(f"\n{caption}\n")
		for y in range(0, len(matrix), 2):
			line = " "
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
	except ImportError:
		print(f"\n{caption}\n  (QR unavailable; open this URL manually) {url}")
	except Exception as e:
		print(f"\nCould not generate QR code: {e}\n  open manually: {url}")


def mkcert_install_command():
	"""Best-guess (command, package-manager-label) to install mkcert on this
	platform, or (None, None) if no known manager is on PATH."""
	from shutil import which
	if sys.platform == "darwin":
		if which("brew"):
			return (["brew", "install", "mkcert"], "Homebrew")
	elif sys.platform == "win32":
		if which("choco"):
			return (["choco", "install", "mkcert", "-y"], "Chocolatey")
		if which("scoop"):
			return (["scoop", "install", "mkcert"], "Scoop")
	else:  # linux / other unix
		# Most distros package mkcert; pick whichever manager is present.
		if which("apt"):
			return (["sudo", "apt", "install", "-y", "mkcert"], "apt")
		if which("dnf"):
			return (["sudo", "dnf", "install", "-y", "mkcert"], "dnf")
		if which("pacman"):
			return (["sudo", "pacman", "-S", "--noconfirm", "mkcert"], "pacman")
		if which("brew"):
			return (["brew", "install", "mkcert"], "Homebrew")
	return (None, None)


def manual_install_hint():
	"""Platform-appropriate manual install instructions for mkcert."""
	if sys.platform == "darwin":
		return "brew install mkcert  (https://github.com/FiloSottile/mkcert)"
	if sys.platform == "win32":
		return "choco install mkcert  OR  scoop install mkcert  (https://github.com/FiloSottile/mkcert)"
	return "install 'mkcert' via your package manager (https://github.com/FiloSottile/mkcert)"


def require_mkcert():
	"""Ensure mkcert is on PATH, offering to install it if it isn't."""
	from shutil import which
	if which("mkcert") is not None:
		return

	print("mkcert is required but was not found on PATH.")
	cmd, label = mkcert_install_command()
	if cmd is None:
		print(f"  Install it manually:  {manual_install_hint()}")
		sys.exit(1)

	answer = input(f"Install it now with {label} ({' '.join(cmd)})? [y/N] ").strip().lower()
	if answer not in ("y", "yes"):
		print(f"  Install it manually:  {manual_install_hint()}")
		sys.exit(1)

	try:
		subprocess.check_call(cmd)
	except (subprocess.CalledProcessError, KeyboardInterrupt):
		print(f"\nInstall failed. Install it manually:  {manual_install_hint()}")
		sys.exit(1)

	if which("mkcert") is None:
		print("mkcert still not on PATH after install. Open a new terminal and retry.")
		sys.exit(1)


def ca_root_file():
	"""Path to mkcert's root CA cert (rootCA.pem)."""
	caroot = subprocess.run(
		["mkcert", "-CAROOT"], capture_output=True, text=True
	).stdout.strip()
	return Path(caroot) / "rootCA.pem"


def ensure_ca_installed():
	"""Ensure mkcert's local CA exists and is trusted by this machine.
	May prompt for your password to write to the system trust store."""
	if not ca_root_file().exists():
		print("Setting up mkcert local CA (you may be prompted for your password)...")
		subprocess.check_call(["mkcert", "-install"])


def ensure_leaf_cert(local_ip):
	"""Mint a cert/key for this machine's LAN IP (and localhost) if missing."""
	CERT_DIR.mkdir(parents=True, exist_ok=True)
	if CERT_FILE.exists() and KEY_FILE.exists():
		return
	print(f"Minting certificate for {local_ip}...")
	subprocess.check_call([
		"mkcert",
		"-cert-file", str(CERT_FILE),
		"-key-file", str(KEY_FILE),
		local_ip, "localhost", "127.0.0.1",
	])


def start_ca_server(local_ip):
	"""Start a plain-HTTP server that hands out the mkcert root CA, and return
	it running. The CA is the *public* root cert (no secret), so there's no
	reason to limit how many times or to how many devices it's served. leave
	it up alongside the HTTPS server so you can set up multiple devices, and
	tear both down together on Ctrl+C. Caller owns shutdown."""
	ca_file = ca_root_file()
	if not ca_file.exists():
		print(f"Error: root CA not found at {ca_file}")
		sys.exit(1)

	ca_bytes = ca_file.read_bytes()

	class CAHandler(http.server.BaseHTTPRequestHandler):
		def log_message(self, *args):
			pass

		def do_GET(self):
			# Redirect bare visits to the download path so a typo'd / still works.
			if self.path in ("/", "/index.html"):
				self.send_response(302)
				self.send_header("Location", CA_DOWNLOAD_PATH)
				self.end_headers()
				return
			if self.path != CA_DOWNLOAD_PATH:
				self.send_error(404)
				return
			# x-x509-ca-cert makes iOS offer to install it as a CA profile.
			self.send_response(200)
			self.send_header("Content-Type", "application/x-x509-ca-cert")
			self.send_header("Content-Length", str(len(ca_bytes)))
			self.send_header(
				"Content-Disposition", 'attachment; filename="rootCA.pem"'
			)
			self.end_headers()
			try:
				self.wfile.write(ca_bytes)
			except (BrokenPipeError, ConnectionResetError):
				return

	port = find_available_port(CERT_HTTP_PORT)
	if port is None:
		print(f"Error: no free port near {CERT_HTTP_PORT} for the CA server.")
		sys.exit(1)
	http.server.HTTPServer.allow_reuse_address = True
	httpd = http.server.HTTPServer(("", port), CAHandler)
	threading.Thread(target=httpd.serve_forever, daemon=True).start()

	cert_url = f"http://{local_ip}:{port}{CA_DOWNLOAD_PATH}"
	print("=" * 69)
	print("STEP 1: install + trust the local CA on each device (first time only)")
	print("=" * 69)
	print_qr_code(cert_url, "Scan to download the root certificate:")
	print(f"  {cert_url}")
	print("\nOn iOS, after downloading:")
	print("  • Settings → General → VPN & Device Management → install the profile")
	print("  • Settings → General → About → Certificate Trust Settings →")
	print("    toggle ON full trust for the mkcert CA")
	print("\nOn Android, after downloading:")
	print("  • open the downloaded file, or Settings → Security → Encryption &")
	print("    credentials → Install a certificate → CA certificate, then confirm")
	print("  • installing the CA is what makes it trusted; there's no separate")
	print("    trust toggle (exact menu names vary by version/manufacturer)")
	print("\n(skip this step on a device that already trusts the CA from a previous run)")
	return httpd


class TLSThreadingServer(socketserver.ThreadingTCPServer):
	"""Threading server that negotiates TLS in the worker thread, so
	handshakes run in parallel."""
	daemon_threads = True
	allow_reuse_address = True
	# default backlog of 5 drops connections when a device precaches in bursts
	request_queue_size = 128

	def __init__(self, server_address, handler_cls, ssl_context):
		self.ssl_context = ssl_context
		super().__init__(server_address, handler_cls)

	def process_request_thread(self, request, client_address):
		try:
			request.settimeout(20)  # cap how long a dead client's handshake lingers
			request = self.ssl_context.wrap_socket(request, server_side=True)
			request.settimeout(None)
		except (ssl.SSLError, OSError):
			# Untrusted CA, a probe, or a client that walked away.
			self.shutdown_request(request)
			return
		super().process_request_thread(request, client_address)


def serve_https(local_ip, base_path, ca_httpd=None):
	"""Serve SCRIPT_DIR over HTTPS for PWA installation, mounted under
	base_path so the installed app's start_url resolves. Runs until Ctrl+C,
	then also shuts down the CA HTTP server (if given)."""
	os.chdir(SCRIPT_DIR)

	# Rescan /mix periodically so edits made on disk reach connected browser
	# tabs over the SSE stream, same as serve.py.
	serve.start_rescan_ticker()

	# Subclass serve.py's handler so editing works over HTTPS too: it adds the
	# SSE change stream (/events), reorder save (POST /tracks), drag-drop
	# upload (PUT /upload/<name>), and delete (DELETE /tracks/<name>). Those
	# endpoints are root-absolute, so base_path stripping (GET-only) doesn't
	# touch them.
	class QuietHandler(serve.TrackRequestHandler):
		def end_headers(self):
			self.send_header("Cache-Control", "no-cache")
			super().end_headers()

		def log_message(self, *args):
			pass

		def handle(self):
			try:
				super().handle()
			except (BrokenPipeError, ConnectionResetError, ssl.SSLError):
				pass

		def translate_path(self, path):
			# Strip the manifest base prefix so /mixapp_name/foo maps to ./foo.
			if base_path != "/" and path.startswith(base_path):
				path = "/" + path[len(base_path):]
			return super().translate_path(path)

		def do_GET(self):
			# Bounce a bare root visit into the app so manual navigation works.
			if base_path != "/" and self.path in ("/", "/index.html"):
				self.send_response(302)
				self.send_header("Location", base_path)
				self.send_header("Content-Length", "0")
				self.end_headers()
				return
			# super() is serve.TrackRequestHandler.do_GET, which handles
			# /events (SSE) and rescans on /mix/tracks.json before serving.
			return super().do_GET()

	ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
	ctx.load_cert_chain(certfile=str(CERT_FILE), keyfile=str(KEY_FILE))

	port = find_available_port(HTTPS_PORT)
	if port is None:
		print(f"Error: no free port near {HTTPS_PORT} for the HTTPS server.")
		if ca_httpd is not None:
			ca_httpd.shutdown()
			ca_httpd.server_close()
		sys.exit(1)

	with TLSThreadingServer(("", port), QuietHandler, ctx) as httpd:
		https_url = f"https://{local_ip}:{port}{base_path}"

		print("\n" + "=" * 59)
		print("STEP 2: install your mixapp (once the device trusts the CA)")
		print("=" * 59)
		print_qr_code(https_url, "Scan to open your mixapp over HTTPS:")
		print(f"  {https_url}")
		print("\nThen install it as a PWA: https://hunterirving.github.io/web_workshop/pages/pwa")
		print("\nPress Ctrl+C to stop the server(s)")

		try:
			httpd.serve_forever()
		except KeyboardInterrupt:
			print("\n\nShutting down...")
		finally:
			if ca_httpd is not None:
				ca_httpd.shutdown()
				ca_httpd.server_close()


def caroot_dir():
	"""Path to mkcert's CAROOT folder (holds rootCA.pem and rootCA-key.pem)."""
	caroot = subprocess.run(
		["mkcert", "-CAROOT"], capture_output=True, text=True
	).stdout.strip()
	return Path(caroot) if caroot else None


def reset_certs():
	"""Opt-in teardown, in two stages so it's safe alongside other mkcert use.

	mkcert keeps ONE shared CA per machine, so anything else you run with
	mkcert trusts the same CA. Stage 1 removes only THIS tool's own leaf certs
	(always safe). Stage 2 removes the shared mkcert CA itself (untrust + optional
	key deletion). Guarded, because it affects every project that uses
	mkcert, not just this one."""
	from shutil import rmtree, which

	# Stage 1: our own leaf certs.
	if CERT_DIR.exists():
		rmtree(CERT_DIR)
		print(f"Removed this tool's local certificates ({CERT_DIR}).")
	else:
		print("No local certificates to remove.")

	# Stage 2: the shared mkcert CA. Skip entirely unless asked, since other
	# projects on this machine may rely on it and we can't detect them.
	print(
		"\nThe mkcert CA itself is SHARED across everything you use mkcert for"
		" on this computer, not just this tool. Leaving it installed is normal."
	)
	answer = input(
		"Also remove the shared mkcert CA (untrust it system-wide)? [y/N] "
	).strip().lower()
	if answer not in ("y", "yes"):
		print("Left the mkcert CA in place.")
		return

	if which("mkcert"):
		try:
			subprocess.check_call(["mkcert", "-uninstall"])
			print("Stopped this computer from trusting the mkcert CA.")
		except subprocess.CalledProcessError as e:
			print(f"mkcert -uninstall failed: {e}")

	# mkcert -uninstall removes trust but does NOT delete the CA. The private key
	# (rootCA-key.pem) is the sensitive material, so offer to delete it too, with
	# a separate confirmation since it's irreversible and shared.
	caroot = caroot_dir()
	if caroot and (caroot / "rootCA-key.pem").exists():
		print(
			"\nThe CA's PRIVATE KEY is still on disk at:\n"
			f"  {caroot}\n"
			"Per mkcert: \"the rootCA-key.pem file ... gives complete power to\n"
			"intercept secure requests from your machine. Do not share it.\"\n"
			"Deleting it removes the shared CA entirely; future mkcert use\n"
			"(here or in any project) will generate a brand-new one."
		)
		ans2 = input("Delete the CA key + folder now? [y/N] ").strip().lower()
		if ans2 in ("y", "yes"):
			rmtree(caroot)
			print(f"Removed {caroot}")
		else:
			print("Left the CA key in place.")

	print("\nNote: this does NOT touch any device; remove or untrust the CA\n"
		"there separately (see the instructions printed during install).")


def start():
	require_mkcert()

	local_ip = get_local_ip()
	if not local_ip:
		print("Error: could not determine this machine's LAN IP.")
		print("Make sure you're connected to a network and try again.")
		sys.exit(1)

	base_path = manifest_base_path()
	if not MANIFEST_FILE.exists():
		print("Warning: manifest.json not found. Run ./build.py first so the\n"
			"PWA is installable. Serving at root for now.\n")

	ensure_ca_installed()
	ensure_leaf_cert(local_ip)
	ca_httpd = start_ca_server(local_ip)
	serve_https(local_ip, base_path, ca_httpd=ca_httpd)


def main():
	if "--in-venv" not in sys.argv:
		run_in_venv()
	else:
		try:
			if "--reset" in sys.argv:
				reset_certs()
			else:
				start()
		except KeyboardInterrupt:
			print("\nCancelled.")
			sys.exit(130)


if __name__ == "__main__":
	main()
