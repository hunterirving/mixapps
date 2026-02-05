#!/usr/bin/env python3
"""
Scans /mix directory and populates tracks.json with metadata
Supports MP3, M4A, OGG, FLAC, and WAV formats
Automatically manages a virtual environment for dependencies
"""

import os
import sys
import subprocess
import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.absolute()
VENV_DIR = SCRIPT_DIR / "venv"
MIX_DIR = SCRIPT_DIR / "mix"
OUTPUT_FILE = MIX_DIR / "tracks.json"
REQUIREMENTS_FILE = SCRIPT_DIR / "requirements.txt"


def setup_venv():
	"""Create and setup virtual environment if it doesn't exist"""
	# Determine the path to pip and python in the venv
	if sys.platform == "win32":
		pip_path = VENV_DIR / "Scripts" / "pip"
		python_path = VENV_DIR / "Scripts" / "python"
	else:
		pip_path = VENV_DIR / "bin" / "pip"
		python_path = VENV_DIR / "bin" / "python3"

	# Check if venv needs to be created or recreated
	if not VENV_DIR.exists() or not python_path.exists():
		if VENV_DIR.exists():
			print("Virtual environment incomplete, recreating...")
			import shutil
			shutil.rmtree(VENV_DIR)
		else:
			print("Creating virtual environment...")

		try:
			subprocess.check_call([sys.executable, "-m", "venv", str(VENV_DIR)])
			print("Virtual environment created successfully.")
		except subprocess.CalledProcessError as e:
			print(f"Error creating virtual environment: {e}")
			sys.exit(1)

	# Ensure pip is available (sometimes venv doesn't include it)
	if not pip_path.exists():
		print("Installing pip in virtual environment...")
		try:
			subprocess.check_call([str(python_path), "-m", "ensurepip", "--upgrade"])
		except subprocess.CalledProcessError as e:
			print(f"Error ensuring pip: {e}")
			sys.exit(1)

	# Install requirements if requirements.txt exists
	if REQUIREMENTS_FILE.exists():
		print("Installing dependencies from requirements.txt...")
		try:
			subprocess.check_call([str(python_path), "-m", "pip", "install", "-q", "-r", str(REQUIREMENTS_FILE)])
			print("Dependencies installed successfully.")
		except subprocess.CalledProcessError as e:
			print(f"Error installing dependencies: {e}")
			sys.exit(1)

	return python_path


def run_in_venv():
	"""Re-run this script in the virtual environment"""
	python_path = setup_venv()

	# Re-run this script with the venv Python
	print("Running scanner in virtual environment...\n")
	subprocess.check_call([str(python_path), __file__, "--in-venv"])
	sys.exit(0)


def scan_tracks():
	"""Main function to scan audio files and generate tracks.json"""
	# Import mutagen here (only after venv is active)
	try:
		from mutagen import File as MutagenFile
	except ImportError:
		print("Error: mutagen library not found. Please check your installation.")
		sys.exit(1)

	# Supported audio formats
	SUPPORTED_EXTENSIONS = ('.mp3', '.m4a', '.ogg', '.flac', '.wav')

	# Check if tracks directory exists, create if it doesn't
	if not MIX_DIR.exists():
		print(f"Creating {MIX_DIR.name} directory...")
		MIX_DIR.mkdir(parents=True, exist_ok=True)
		print(f"✓ {MIX_DIR.name} directory created.")
		print(f"\nAdd audio files to the {MIX_DIR.name} directory and run this script again.")
		print(f"Supported formats: {', '.join(SUPPORTED_EXTENSIONS)}")
		sys.exit(0)

	# Check if tracks.json already exists
	if OUTPUT_FILE.exists():
		response = input(f"{OUTPUT_FILE.name} already exists. Overwrite? (y/n): ").lower().strip()
		if response != 'y':
			print(f"Scan cancelled. {OUTPUT_FILE.name} was not modified.")
			sys.exit(0)

	# Find all supported audio files
	audio_files = [f for f in MIX_DIR.iterdir() if f.suffix.lower() in SUPPORTED_EXTENSIONS]

	if not audio_files:
		print(f"No audio files found in {MIX_DIR}")
		print(f"\nPlease add audio files to the {MIX_DIR.name} directory and run this script again.")
		print(f"Supported formats: {', '.join(SUPPORTED_EXTENSIONS)}")
		sys.exit(0)

	print(f"Found {len(audio_files)} audio file(s). Extracting metadata...\n")

	tracks = []

	for audio_file in sorted(audio_files):
		try:
			audio = MutagenFile(audio_file, easy=True)

			title = None
			artist = None

			if audio and audio.tags:
				title = audio.tags.get('title', [None])[0]
				artist = audio.tags.get('artist', [None])[0]

			# Fallback to filename for title if not found
			if not title:
				title = audio_file.stem  # filename without extension

			# Fallback to "Unknown Artist" if not found
			if not artist:
				artist = "Unknown Artist"

			track_info = {
				"title": title,
				"artist": artist,
				"filename": audio_file.name
			}

			tracks.append(track_info)
			print(f"✓ {track_info['artist']} - {track_info['title']}")

		except Exception as e:
			print(f"✗ Error reading {audio_file.name}: {e}")
			continue

	# Check if ALL titles start with numbers
	# If so, strip the leading numbers from all titles
	import re
	all_have_leading_numbers = all(
		re.match(r'^\d+\s*[-.]?\s*', track['title'])
		for track in tracks
	)

	if all_have_leading_numbers and tracks:
		print("\nDetected track numbers in all titles. Stripping them...")
		for track in tracks:
			original_title = track['title']
			# Remove leading number pattern
			cleaned_title = re.sub(r'^\d+\s*[-.]?\s*', '', original_title)
			if cleaned_title:  # Only update if something remains
				track['title'] = cleaned_title
				if cleaned_title != original_title:
					print(f"  {original_title} → {cleaned_title}")

	if not tracks:
		print("\nNo valid audio files could be processed.")
		sys.exit(1)

	# Write to tracks.json
	try:
		with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
			json.dump(tracks, f, indent="\t", ensure_ascii=False)

		print(f"\n✓ Successfully generated {OUTPUT_FILE.name} with {len(tracks)} track(s).")

	except Exception as e:
		print(f"\nError writing {OUTPUT_FILE.name}: {e}")
		sys.exit(1)


def main():
	"""Main entry point"""
	# Check if we're already running in venv
	if "--in-venv" not in sys.argv:
		run_in_venv()
	else:
		scan_tracks()


if __name__ == "__main__":
	main()
