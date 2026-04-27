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


def setup_venv():
	"""Create and set up virtual environment if it doesn't exist"""
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

	check = subprocess.run(
		[str(python_path), "-c", "import mutagen"],
		capture_output=True
	)
	if check.returncode != 0:
		try:
			subprocess.check_call([str(python_path), "-m", "pip", "install", "-q", "mutagen"])
		except subprocess.CalledProcessError:
			print("Note: Could not install mutagen (offline?). Metadata will be derived from filenames.\n")

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
		from mutagen import File as MutagenFile  # type: ignore
		has_mutagen = True
	except ImportError:
		MutagenFile = None
		has_mutagen = False
		print("Mutagen not available. Metadata will be derived from filenames.\n")

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

	# Find all supported audio files
	audio_files = [f for f in MIX_DIR.iterdir() if f.suffix.lower() in SUPPORTED_EXTENSIONS]

	if not audio_files:
		print(f"No audio files found in {MIX_DIR}")
		print(f"\nPlease add audio files to the {MIX_DIR.name} directory and run this script again.")
		print(f"Supported formats: {', '.join(SUPPORTED_EXTENSIONS)}")
		sys.exit(0)

	print(f"Found {len(audio_files)} audio file(s). Extracting metadata...\n")

	existing_tracks = []
	if OUTPUT_FILE.exists():
		try:
			with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
				loaded = json.load(f)
			if isinstance(loaded, list):
				existing_tracks = loaded
		except (json.JSONDecodeError, OSError) as e:
			print(f"Warning: could not read existing {OUTPUT_FILE.name} ({e}). Starting fresh.\n")

	existing_by_filename = {
		t['filename']: t for t in existing_tracks
		if isinstance(t, dict) and 'filename' in t
	}
	on_disk_filenames = {f.name for f in audio_files}
	files_by_name = {f.name: f for f in audio_files}

	def read_metadata(audio_file):
		title = None
		artist = None
		if has_mutagen:
			audio = MutagenFile(audio_file, easy=True)
			if audio and audio.tags:
				title = audio.tags.get('title', [None])[0]
				artist = audio.tags.get('artist', [None])[0]
		if not title:
			title = audio_file.stem
		if not artist:
			artist = "Unknown Artist"
		return {"title": title, "artist": artist, "filename": audio_file.name}

	tracks = []
	removed = []
	for entry in existing_tracks:
		if not isinstance(entry, dict) or 'filename' not in entry:
			continue
		if entry['filename'] in on_disk_filenames:
			tracks.append(entry)
		else:
			removed.append(entry['filename'])

	new_files = sorted(
		(files_by_name[name] for name in on_disk_filenames if name not in existing_by_filename),
		key=lambda f: f.name,
	)
	new_tracks = []
	for audio_file in new_files:
		try:
			new_tracks.append(read_metadata(audio_file))
		except Exception as e:
			print(f"✗ Error reading {audio_file.name}: {e}")

	for track in new_tracks:
		print(f"+ {track['artist']} - {track['title']}")
	for filename in removed:
		print(f"- {filename} (removed; no longer on disk)")
	if not new_tracks and not removed:
		print("No changes — tracks.json already matches /mix.")

	tracks.extend(new_tracks)

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
