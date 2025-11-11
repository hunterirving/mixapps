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
import subprocess
from pathlib import Path

DEFAULT_PORT = 8000
SCRIPT_DIR = Path(__file__).parent.absolute()
VENV_DIR = SCRIPT_DIR / "venv"
REQUIREMENTS_FILE = SCRIPT_DIR / "requirements.txt"


def setup_venv():
	"""Create and setup virtual environment if it doesn't exist"""
	if not VENV_DIR.exists():
		print("Creating virtual environment...")
		try:
			subprocess.check_call([sys.executable, "-m", "venv", str(VENV_DIR)])
			print("Virtual environment created successfully.")
		except subprocess.CalledProcessError as e:
			print(f"Error creating virtual environment: {e}")
			sys.exit(1)

	# Determine the path to pip in the venv
	if sys.platform == "win32":
		pip_path = VENV_DIR / "Scripts" / "pip"
		python_path = VENV_DIR / "Scripts" / "python"
	else:
		pip_path = VENV_DIR / "bin" / "pip"
		python_path = VENV_DIR / "bin" / "python3"

	# Install requirements if requirements.txt exists
	if REQUIREMENTS_FILE.exists():
		print("Installing dependencies from requirements.txt...")
		try:
			subprocess.check_call([str(pip_path), "install", "-q", "-r", str(REQUIREMENTS_FILE)])
			print("Dependencies installed successfully.\n")
		except subprocess.CalledProcessError as e:
			print(f"Error installing dependencies: {e}")
			sys.exit(1)

	return python_path


def run_in_venv():
	"""Re-run this script in the virtual environment"""
	python_path = setup_venv()

	# Re-run this script with the venv Python
	subprocess.check_call([str(python_path), __file__, "--in-venv"])
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

		# Print QR code using block characters
		# Use full block (█) for black and space for white
		print("\nScan to connect:")
		for row in matrix:
			line = ""
			for cell in row:
				line += "██" if cell else "  "
			print(line)
		print()
	except ImportError:
		print("\nQR code generation unavailable (qrcode library not installed)")
	except Exception as e:
		print(f"\nCould not generate QR code: {e}")


def start_server():
	"""Start the HTTP server (runs after venv is set up)"""
	# Change to script directory
	os.chdir(SCRIPT_DIR)

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
		def log_message(self, format, *args):
			pass

		def handle(self):
			"""Handle requests and suppress broken pipe errors"""
			try:
				super().handle()
			except (BrokenPipeError, ConnectionResetError):
				# Browser cancelled the request (normal for media streaming/preloading)
				pass

	try:
		with socketserver.TCPServer(("", port), QuietHandler) as httpd:
			local_url = f"http://localhost:{port}"
			network_url = f"http://{local_ip}:{port}"

			print("=" * 60)
			print("💿 vibe capsule")
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
