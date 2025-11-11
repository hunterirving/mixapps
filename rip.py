#!/usr/bin/env python3
"""
CD Ripper - Rips audio CDs to MP3 files in /tracks directory
Uses system tools: ffmpeg/ffprobe (no Python dependencies needed)
"""

import os
import sys
import subprocess
import shutil
import time
from pathlib import Path
import platform

SCRIPT_DIR = Path(__file__).parent.absolute()
TRACKS_DIR = SCRIPT_DIR / "tracks"


def check_ffmpeg():
	"""Check if ffmpeg is installed, offer to install if not"""
	try:
		subprocess.check_output(['ffmpeg', '-version'], stderr=subprocess.DEVNULL)
		return True
	except (subprocess.CalledProcessError, FileNotFoundError):
		return False


def install_ffmpeg():
	"""Attempt to install ffmpeg based on the platform"""
	system = platform.system()

	print("\nffmpeg is required to convert audio files to MP3.")
	print("Would you like to install it now? (requires admin/sudo privileges)")
	response = input("Install ffmpeg? (y/n): ").lower().strip()

	if response != 'y':
		print("Cannot proceed without ffmpeg. Exiting.")
		sys.exit(1)

	try:
		if system == "Darwin":  # macOS
			print("\nAttempting to install ffmpeg via Homebrew...")
			# Check if brew is installed
			try:
				subprocess.check_output(['brew', '--version'], stderr=subprocess.DEVNULL)
			except FileNotFoundError:
				print("Error: Homebrew is not installed.")
				print("Please install Homebrew from https://brew.sh or install ffmpeg manually.")
				sys.exit(1)
			subprocess.check_call(['brew', 'install', 'ffmpeg'])

		elif system == "Linux":
			print("\nAttempting to install ffmpeg...")
			# Try to detect package manager
			if shutil.which('apt'):
				subprocess.check_call(['sudo', 'apt', 'update'])
				subprocess.check_call(['sudo', 'apt', 'install', '-y', 'ffmpeg'])
			elif shutil.which('dnf'):
				subprocess.check_call(['sudo', 'dnf', 'install', '-y', 'ffmpeg'])
			elif shutil.which('pacman'):
				subprocess.check_call(['sudo', 'pacman', '-S', '--noconfirm', 'ffmpeg'])
			else:
				print("Error: Could not detect package manager.")
				print("Please install ffmpeg manually for your distribution.")
				sys.exit(1)

		elif system == "Windows":
			print("\nAutomatic installation not supported on Windows.")
			print("Please download ffmpeg from https://ffmpeg.org/download.html")
			print("and add it to your PATH.")
			sys.exit(1)
		else:
			print(f"\nAutomatic installation not supported on {system}.")
			print("Please install ffmpeg manually.")
			sys.exit(1)

		print("✓ ffmpeg installed successfully.")
		return True

	except subprocess.CalledProcessError as e:
		print(f"Error installing ffmpeg: {e}")
		print("Please install ffmpeg manually.")
		sys.exit(1)


def find_cd_mount():
	"""Find the mount point of an audio CD"""
	system = platform.system()

	if system == "Darwin":  # macOS
		# Check /Volumes for CD mounts
		volumes = Path("/Volumes")
		if not volumes.exists():
			return None

		# Look for CD mounts (typically Audio CD or similar)
		for vol in volumes.iterdir():
			if vol.is_dir():
				# Check if this volume contains audio files
				audio_files = list(vol.glob("*.aiff")) + list(vol.glob("*.aif"))
				if audio_files:
					return vol
		return None

	elif system == "Linux":
		# Check common mount points
		mount_points = [
			Path("/media") / os.getlogin(),
			Path("/run/media") / os.getlogin(),
			Path("/mnt"),
		]

		for mount_base in mount_points:
			if mount_base.exists():
				for vol in mount_base.iterdir():
					if vol.is_dir():
						# Check for audio files
						audio_files = (list(vol.glob("*.wav")) +
									  list(vol.glob("*.aiff")) +
									  list(vol.glob("*.aif")))
						if audio_files:
							return vol
		return None

	else:
		print(f"Platform {system} not fully supported yet.")
		return None


def natural_sort_key(path):
	"""Generate a key for natural sorting of filenames with numbers"""
	import re
	# Split filename into text and number parts
	parts = []
	for part in re.split(r'(\d+)', str(path.name)):
		if part.isdigit():
			parts.append(int(part))  # Convert numbers to integers for proper sorting
		else:
			parts.append(part.lower())  # Lowercase for case-insensitive sorting
	return parts


def get_audio_files(mount_point):
	"""Get all audio files from the CD mount point"""
	audio_extensions = ['*.wav', '*.aiff', '*.aif', '*.flac', '*.mp3']
	audio_files = []

	for ext in audio_extensions:
		audio_files.extend(mount_point.glob(ext))
		# Also check subdirectories (some CDs have nested structures)
		audio_files.extend(mount_point.glob(f"*/{ext}"))

	# Sort using natural sorting (handles numbers correctly)
	return sorted(audio_files, key=natural_sort_key)


def get_audio_duration(input_file):
	"""Get the duration of an audio file in seconds using ffprobe"""
	try:
		cmd = [
			'ffprobe',
			'-v', 'error',
			'-show_entries', 'format=duration',
			'-of', 'default=noprint_wrappers=1:nokey=1',
			str(input_file)
		]
		result = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
		return float(result.decode().strip())
	except (subprocess.CalledProcessError, ValueError):
		return None


def print_progress_bar(progress, eta_str="", width=40):
	"""Print a progress bar using block characters with optional ETA"""
	filled = int(width * progress)
	bar = '█' * filled + '░' * (width - filled)
	percent = int(progress * 100)
	
	output = f"\r\033[K[{bar}] {percent}%"
	if eta_str:
		output += f" · Total ETA: {eta_str}"
	print(output, end='', flush=True)


def convert_to_mp3(input_file, output_file, track_num, title, artist,
                   total_size, processed_size, start_time):
	"""Convert an audio file to MP3 using ffmpeg with progress bar and ETA"""
	try:
		duration = get_audio_duration(input_file)

		cmd = [
			'ffmpeg', '-i', str(input_file),
			'-codec:a', 'libmp3lame', '-qscale:a', '2',
			'-metadata', f'track={track_num}',
			'-metadata', f'title={title}',
			'-metadata', f'artist={artist}',
			'-progress', 'pipe:1', '-y',
			str(output_file)
		]

		process = subprocess.Popen(cmd, stdout=subprocess.PIPE,
		                          stderr=subprocess.DEVNULL, universal_newlines=True)
		last_percent = -1
		last_eta_str = ""

		for line in process.stdout:
			if line.startswith('out_time_ms='):
				try:
					microseconds = int(line.split('=')[1])
					current_time = microseconds / 1_000_000

					if duration and duration > 0:
						progress = min(current_time / duration, 1.0)
						current_percent = int(progress * 100)

						# Calculate total ETA
						total_processed = processed_size + input_file.stat().st_size * progress
						if total_processed > 0:
							elapsed = time.time() - start_time
							bytes_per_sec = total_processed / elapsed
							eta_sec = (total_size - total_processed) / bytes_per_sec if bytes_per_sec > 0 else 0
							eta_str = f"{int(eta_sec / 60)}m {int(eta_sec % 60):02d}s"
						else:
							eta_str = ""

						# Update if either percentage or ETA changed
						if current_percent != last_percent or eta_str != last_eta_str:
							print_progress_bar(progress, eta_str)
							last_percent = current_percent
							last_eta_str = eta_str
				except (ValueError, IndexError):
					pass

		process.wait()
		if process.returncode == 0:
			print_progress_bar(1.0)
			print()
			return True
		else:
			print()
			return False

	except Exception as e:
		print(f"\n     Error: {e}")
		return False


def sanitize_filename(filename):
	"""Sanitize filename to remove invalid characters"""
	# Remove extension
	name = Path(filename).stem
	# Replace invalid characters
	invalid_chars = '<>:"|?*\\'
	for char in invalid_chars:
		name = name.replace(char, '_')
	return name


def rip_cd():
	"""Main function to rip CD to MP3 files"""
	print("=" * 60)
	print("💿 vibe capsule - CD Ripper")
	print("=" * 60)

	# Check for ffmpeg
	if not check_ffmpeg():
		print("\n✗ ffmpeg not found.")
		install_ffmpeg()
	else:
		print("\n✓ ffmpeg found.")

	# Create tracks directory if it doesn't exist
	if not TRACKS_DIR.exists():
		print(f"\nCreating {TRACKS_DIR.name} directory...")
		TRACKS_DIR.mkdir(parents=True, exist_ok=True)

	# Find CD mount point
	print("\nSearching for audio CD...")
	mount_point = find_cd_mount()

	if not mount_point:
		print("✗ No audio CD found.")
		print("\nPlease insert an audio CD and try again.")
		print("\nNote: On some systems, you may need to manually mount the CD first.")
		if platform.system() == "Linux":
			print("\nOn Linux: sudo mount /dev/cdrom /mnt/cdrom")
		sys.exit(1)

	print(f"✓ Found CD at: {mount_point}")

	# Get audio files from CD
	audio_files = get_audio_files(mount_point)

	if not audio_files:
		print("✗ No audio files found on the CD.")
		sys.exit(1)

	print(f"✓ Found {len(audio_files)} audio track(s).")

	# Confirm before ripping
	print(f"\nThis will copy and convert {len(audio_files)} tracks to MP3 format.")
	print(f"Output directory: {TRACKS_DIR}")
	
	# Prompt for artist name
	print("\nEnter the artist name for this album.")
	artist = input("Artist (press Enter for 'Unknown Artist'): ").strip()
	if not artist:
		artist = "Unknown Artist"

	print("\nRipping CD...")
	print("-" * 60)

	success_count = 0
	start_time = time.time()
	total_size = sum(f.stat().st_size for f in audio_files)
	processed_size = 0
	padding_width = len(str(len(audio_files)))

	for idx, audio_file in enumerate(audio_files, start=1):
		base_name = sanitize_filename(audio_file.name)
		
		# Remove leading track number to avoid duplicates like "01 1 Track"
		import re
		cleaned_name = re.sub(r'^\d+\s*[-.]?\s*', '', base_name) or base_name
		
		padded_idx = str(idx).zfill(padding_width)
		output_file = TRACKS_DIR / f"{padded_idx} {cleaned_name}.mp3"

		# Handle duplicate filenames
		counter = 1
		while output_file.exists():
			output_file = TRACKS_DIR / f"{padded_idx} {cleaned_name}_{counter}.mp3"
			counter += 1

		print(f"[{idx}/{len(audio_files)}] {audio_file.name} -> {output_file.name}")

		if audio_file.suffix.lower() == '.mp3':
			try:
				shutil.copy2(audio_file, output_file)
				success_count += 1
				print(f"[████████████████████████████████████████] 100%")
				print(f"✓ Copied")
			except Exception as e:
				print(f"✗ Error: {e}")
		else:
			if convert_to_mp3(audio_file, output_file, idx, cleaned_name, artist,
			                 total_size, processed_size, start_time):
				success_count += 1
				print(f"✓ Converted to MP3")
			else:
				print(f"✗ Conversion failed")

		processed_size += audio_file.stat().st_size

	# Calculate total time
	total_time = time.time() - start_time
	total_minutes = int(total_time / 60)
	total_secs = int(total_time % 60)

	print("-" * 60)
	print(f"\n✓ Successfully ripped {success_count}/{len(audio_files)} tracks in {total_minutes}m {total_secs}s.")

	if success_count > 0:
		print(f"\nTracks saved to: {TRACKS_DIR}")
		print("\nNext steps:")
		print("  1. Run scan.py to generate tracks.json with metadata")
		print("  2. Run host.py to test your mixtape locally")

		# Eject the CD
		print("\nEjecting CD...")
		try:
			system = platform.system()
			if system == "Darwin":  # macOS
				subprocess.run(['diskutil', 'eject', str(mount_point)], check=False)
			elif system == "Linux":
				subprocess.run(['eject', str(mount_point)], check=False)
			print("✓ CD ejected")
		except Exception as e:
			print(f"Note: Could not auto-eject CD: {e}")
			print("You can manually eject it.")


def main():
	"""Main entry point"""
	rip_cd()


if __name__ == "__main__":
	main()