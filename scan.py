#!/usr/bin/env python3
"""
MP3 Scanner - Scans /tracks directory and generates tracks.json with metadata
Automatically manages a virtual environment for dependencies
"""

import os
import sys
import subprocess
import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.absolute()
VENV_DIR = SCRIPT_DIR / "venv"
TRACKS_DIR = SCRIPT_DIR / "tracks"
OUTPUT_FILE = TRACKS_DIR / "tracks.json"
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
	"""Main function to scan MP3 files and generate tracks.json"""
	# Import mutagen here (only after venv is active)
	try:
		from mutagen.mp3 import MP3
		from mutagen.id3 import ID3
	except ImportError:
		print("Error: mutagen library not found. Please check your installation.")
		sys.exit(1)

	# Check if tracks directory exists, create if it doesn't
	if not TRACKS_DIR.exists():
		print(f"Creating {TRACKS_DIR.name} directory...")
		TRACKS_DIR.mkdir(parents=True, exist_ok=True)
		print(f"✓ {TRACKS_DIR.name} directory created.")
		print(f"\nPlease add MP3 files to the {TRACKS_DIR.name} directory and run this script again.")
		sys.exit(0)

	# Check if tracks.json already exists
	if OUTPUT_FILE.exists():
		response = input(f"{OUTPUT_FILE.name} already exists. Overwrite? (y/n): ").lower().strip()
		if response != 'y':
			print(f"Scan cancelled. {OUTPUT_FILE.name} was not modified.")
			sys.exit(0)

	# Find all MP3 files
	mp3_files = list(TRACKS_DIR.glob("*.mp3"))

	if not mp3_files:
		print(f"No MP3 files found in {TRACKS_DIR}")
		print(f"\nPlease add MP3 files to the {TRACKS_DIR.name} directory and run this script again.")
		sys.exit(0)

	print(f"Found {len(mp3_files)} MP3 file(s). Extracting metadata...\n")

	tracks = []

	for mp3_file in sorted(mp3_files):
		try:
			audio = MP3(mp3_file)

			# Try to get ID3 tags
			title = None
			artist = None

			if audio.tags:
				# Try different title tags
				if 'TIT2' in audio.tags:  # Title
					title = str(audio.tags['TIT2'])

				# Try different artist tags
				if 'TPE1' in audio.tags:  # Artist
					artist = str(audio.tags['TPE1'])

			# Fallback to filename for title if not found
			if not title:
				title = mp3_file.stem  # filename without extension

			# Fallback to "Unknown Artist" if not found
			if not artist:
				artist = "Unknown Artist"

			track_info = {
				"title": title,
				"artist": artist,
				"filename": mp3_file.name
			}

			tracks.append(track_info)
			print(f"✓ {track_info['artist']} - {track_info['title']}")

		except Exception as e:
			print(f"✗ Error reading {mp3_file.name}: {e}")
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
		print("\nNo valid MP3 files could be processed.")
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
