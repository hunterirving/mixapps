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


def setup_venv(packages=("mutagen",)):
	"""Create the shared venv if missing and ensure each package is installed.
	Returns the path to the venv Python interpreter."""
	if sys.platform == "win32":
		pip_path = VENV_DIR / "Scripts" / "pip"
		python_path = VENV_DIR / "Scripts" / "python"
	else:
		pip_path = VENV_DIR / "bin" / "pip"
		python_path = VENV_DIR / "bin" / "python3"

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

	if not pip_path.exists():
		print("Installing pip in virtual environment...")
		try:
			subprocess.check_call([str(python_path), "-m", "ensurepip", "--upgrade"])
		except subprocess.CalledProcessError as e:
			print(f"Error ensuring pip: {e}")
			sys.exit(1)

	for pkg in packages:
		check = subprocess.run(
			[str(python_path), "-c", f"import {pkg}"],
			capture_output=True
		)
		if check.returncode != 0:
			try:
				subprocess.check_call([str(python_path), "-m", "pip", "install", "-q", pkg])
			except subprocess.CalledProcessError:
				print(f"Note: Could not install {pkg} (offline?).\n")

	return python_path


def bootstrap(script_path, packages=("mutagen",), sentinel="--in-venv"):
	"""Ensure the calling script is running inside the shared venv
	with `packages` available. Re-execs through the venv Python on first call;
	returns immediately on the second pass once the sentinel is in argv.

	Each script that uses this should pass its own __file__ as script_path."""
	if sentinel in sys.argv:
		sys.argv.remove(sentinel)
		return
	python_path = setup_venv(packages)
	try:
		result = subprocess.run([str(python_path), script_path, sentinel, *sys.argv[1:]])
		sys.exit(result.returncode)
	except KeyboardInterrupt:
		sys.exit(130)


def run_in_venv():
	"""Re-run this script in the virtual environment (CLI use of scan.py)."""
	python_path = setup_venv()
	print("Running scanner in virtual environment...\n")
	subprocess.check_call([str(python_path), __file__, "--in-venv"])
	sys.exit(0)


SUPPORTED_EXTENSIONS = ('.mp3', '.m4a', '.ogg', '.flac', '.wav')

_INVALID_FILENAME_CHARS = '<>:"/\\|?*'


def _sanitize_filename(name):
	for char in _INVALID_FILENAME_CHARS:
		name = name.replace(char, '')
	return name.strip()


def _write_tags(audio_file, artist, title, MutagenFile):
	"""Write artist/title tags to disk if they don't already match. Returns
	True if anything was written."""
	try:
		audio = MutagenFile(audio_file, easy=True)
		if audio is None:
			return False
		if audio.tags is None:
			audio.add_tags()
		current_title = audio.tags.get('title', [None])[0]
		current_artist = audio.tags.get('artist', [None])[0]
		if current_title == title and current_artist == artist:
			return False
		audio.tags['title'] = title
		audio.tags['artist'] = artist
		audio.save()
		return True
	except Exception:
		return False


def _canonicalize(tracks, has_mutagen, MutagenFile, silent):
	"""Rename files to 'Artist – Title.ext' and sync ID3 tags so disk state
	matches tracks.json metadata. Mutates `tracks` in place; returns a list
	of {from, to} renames so callers can migrate any external state (eg.
	preloaded blob URLs in connected browser tabs)."""
	renames = []
	for entry in tracks:
		old_filename = entry['filename']
		ext = Path(old_filename).suffix
		artist = _sanitize_filename(entry['artist'])
		title = _sanitize_filename(entry['title'])
		new_filename = f"{artist} – {title}{ext}"

		old_path = MIX_DIR / old_filename
		new_path = MIX_DIR / new_filename

		# Keep tags aligned with the (possibly hand-edited) tracks.json
		# entry, regardless of whether a rename is needed.
		if has_mutagen and old_path.exists():
			_write_tags(old_path, entry['artist'], entry['title'], MutagenFile)

		if old_filename == new_filename:
			continue
		if not old_path.exists():
			continue
		if new_path.exists():
			# Don't clobber an unrelated file that already occupies the
			# canonical name. Leave the entry pointing at its current file.
			if not silent:
				print(f"  Skipping rename {old_filename} -> {new_filename} (target exists)")
			continue
		try:
			old_path.rename(new_path)
			entry['filename'] = new_filename
			renames.append({'from': old_filename, 'to': new_filename})
			if not silent:
				print(f"  Renamed: {old_filename} -> {new_filename}")
		except Exception as e:
			if not silent:
				print(f"  Error renaming {old_filename}: {e}")
	return renames


def rescan(silent=False):
	"""Reconcile tracks.json with /mix. Renames files to canonical
	'Artist – Title.ext' form when they drift, syncing ID3 tags at the same
	time. Returns (tracks, changed, renames) where renames is a list of
	{from, to} dicts for any files that moved this pass."""
	try:
		from mutagen import File as MutagenFile  # type: ignore
		has_mutagen = True
	except ImportError:
		MutagenFile = None
		has_mutagen = False
		if not silent:
			print("Mutagen not available. Metadata will be derived from filenames.\n")

	if not MIX_DIR.exists():
		MIX_DIR.mkdir(parents=True, exist_ok=True)

	audio_files = [f for f in MIX_DIR.iterdir() if f.suffix.lower() in SUPPORTED_EXTENSIONS]

	existing_tracks = []
	if OUTPUT_FILE.exists():
		try:
			with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
				loaded = json.load(f)
			if isinstance(loaded, list):
				existing_tracks = loaded
		except (json.JSONDecodeError, OSError) as e:
			if not silent:
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
			if not silent:
				print(f"✗ Error reading {audio_file.name}: {e}")

	if not silent:
		for track in new_tracks:
			print(f"+ {track['artist']} - {track['title']}")
		for filename in removed:
			print(f"- {filename} (removed; no longer on disk)")
		if not new_tracks and not removed:
			print("No changes — tracks.json already matches /mix.")

	tracks.extend(new_tracks)

	renames = _canonicalize(tracks, has_mutagen, MutagenFile, silent)

	changed = bool(new_tracks) or bool(removed) or bool(renames)
	if changed or not OUTPUT_FILE.exists():
		try:
			OUTPUT_FILE.write_text(
				json.dumps(tracks, indent='\t', ensure_ascii=False) + '\n',
				encoding='utf-8',
			)
		except Exception as e:
			if not silent:
				print(f"\nError writing {OUTPUT_FILE.name}: {e}")
			raise

	return tracks, changed, renames


def scan_tracks():
	"""CLI entry point: rescan and print a summary."""
	if not MIX_DIR.exists():
		print(f"Creating {MIX_DIR.name} directory...")
		MIX_DIR.mkdir(parents=True, exist_ok=True)
		print(f"✓ {MIX_DIR.name} directory created.")
		print(f"\nAdd audio files to the {MIX_DIR.name} directory and run this script again.")
		print(f"Supported formats: {', '.join(SUPPORTED_EXTENSIONS)}")
		sys.exit(0)

	audio_files = [f for f in MIX_DIR.iterdir() if f.suffix.lower() in SUPPORTED_EXTENSIONS]
	if not audio_files:
		print(f"No audio files found in {MIX_DIR}")
		print(f"\nPlease add audio files to the {MIX_DIR.name} directory and run this script again.")
		print(f"Supported formats: {', '.join(SUPPORTED_EXTENSIONS)}")
		sys.exit(0)

	print(f"Found {len(audio_files)} audio file(s). Extracting metadata...\n")
	tracks, changed, _renames = rescan(silent=False)
	if not tracks:
		print("\nNo valid audio files could be processed.")
		sys.exit(1)
	if changed:
		print(f"\n✓ Updated {OUTPUT_FILE.name} ({len(tracks)} track(s)).")


def main():
	"""Main entry point"""
	# Check if we're already running in venv
	if "--in-venv" not in sys.argv:
		run_in_venv()
	else:
		scan_tracks()


if __name__ == "__main__":
	main()
