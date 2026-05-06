#!/usr/bin/env python3
"""
Rips audio CDs to MP3 files in /mix directory
Uses system tools: ffmpeg/ffprobe (no Python dependencies needed)
"""

import os
import sys

# Hop into the shared venv (managed by scan.py) before doing anything else,
# so scan.rescan() has mutagen available when we call it after ripping.
sys.path.insert(0, str(os.path.dirname(os.path.abspath(__file__))))
import scan
scan.bootstrap(__file__, packages=("mutagen", "discid"))

import subprocess
import shutil
import time
import json
import urllib.request
import urllib.error
from pathlib import Path
import platform

SCRIPT_DIR = Path(__file__).parent.absolute()
MIX_DIR = SCRIPT_DIR / "mix"


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


def check_libdiscid():
	"""Verify the libdiscid C library is loadable via the discid Python package"""
	try:
		import discid
		_ = discid.LIBDISCID_VERSION_STRING
		return True
	except (ImportError, OSError, AttributeError):
		return False


def install_libdiscid():
	"""Attempt to install libdiscid based on the platform. Returns True on success."""
	system = platform.system()

	print("\nlibdiscid is required for CD metadata lookup (artist, album, titles).")
	print("Would you like to install it now? (requires admin/sudo privileges)")
	response = input("Install libdiscid? (y/n): ").lower().strip()

	if response != 'y':
		return False

	try:
		if system == "Darwin":
			try:
				subprocess.check_output(['brew', '--version'], stderr=subprocess.DEVNULL)
			except FileNotFoundError:
				print("\nError: Homebrew is not installed.")
				print("Install Homebrew from https://brew.sh, then run: brew install libdiscid")
				return False
			print("\nInstalling libdiscid via Homebrew...")
			subprocess.check_call(['brew', 'install', 'libdiscid'])

		elif system == "Linux":
			print("\nInstalling libdiscid...")
			if shutil.which('apt'):
				subprocess.check_call(['sudo', 'apt', 'update'])
				subprocess.check_call(['sudo', 'apt', 'install', '-y', 'libdiscid0'])
			elif shutil.which('dnf'):
				subprocess.check_call(['sudo', 'dnf', 'install', '-y', 'libdiscid'])
			elif shutil.which('pacman'):
				subprocess.check_call(['sudo', 'pacman', '-S', '--noconfirm', 'libdiscid'])
			else:
				print("Error: Could not detect package manager.")
				print("Please install libdiscid manually for your distribution.")
				return False

		elif system == "Windows":
			print("\nAutomatic installation not supported on Windows.")
			print("Download libdiscid from https://musicbrainz.org/doc/libdiscid")
			print("and place discid.dll alongside rip.py (or on your PATH).")
			return False
		else:
			print(f"\nAutomatic installation not supported on {system}.")
			print("Please install libdiscid manually.")
			return False

		print("✓ libdiscid installed successfully.")
		return True

	except subprocess.CalledProcessError as e:
		print(f"\nError installing libdiscid: {e}")
		print("You can install it manually, or skip metadata lookup and enter the artist by hand.")
		return False


def lookup_musicbrainz():
	"""Compute disc ID from the default optical device and query MusicBrainz.
	Returns (artist, album, {track_num: title}) or None on any failure."""
	try:
		import discid
	except ImportError:
		return None

	try:
		# discid.read() with no argument uses the platform's default optical device
		disc = discid.read()
	except Exception as e:
		print(f"  Could not read disc ID: {e}")
		return None

	url = f"https://musicbrainz.org/ws/2/discid/{disc.id}?inc=recordings+artist-credits&fmt=json"
	req = urllib.request.Request(url, headers={
		'User-Agent': 'mixapps/1.0 ( https://github.com/hunterirving/mixapps )',
		'Accept': 'application/json',
	})

	try:
		with urllib.request.urlopen(req, timeout=10) as resp:
			data = json.loads(resp.read().decode())
	except urllib.error.HTTPError as e:
		if e.code == 404:
			print("  Disc not found in MusicBrainz database.")
		else:
			print(f"  MusicBrainz lookup failed: HTTP {e.code}")
		return None
	except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
		print(f"  MusicBrainz lookup failed: {e}")
		return None

	releases = data.get('releases', [])
	if not releases:
		return None

	release = releases[0]
	album = release.get('title', '')
	artist = ' & '.join(
		ac.get('name', '') for ac in release.get('artist-credit', [])
		if isinstance(ac, dict) and ac.get('name')
	) or 'Unknown Artist'

	titles = {}
	for medium in release.get('media', []):
		for track in medium.get('tracks', []):
			try:
				num = int(track.get('position') or track.get('number'))
				titles[num] = track.get('title', '')
			except (TypeError, ValueError):
				continue

	return artist, album, titles


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


def print_progress_bar(progress, disc_progress=None, time_str="", width=40, show_disc=True):
	"""Print a progress bar with width-stable percent + disc progress + remaining time"""
	filled = int(width * progress)
	bar = '█' * filled + '░' * (width - filled)
	percent = int(progress * 100)

	output = f"\r\033[K[{bar}] {percent:>2}%"
	if disc_progress is not None:
		if show_disc:
			disc_pct = int(disc_progress * 100)
			output += f"  Total:  {disc_pct}%"
		if time_str:
			output += f" (remaining: {time_str})"
	print(output, end='', flush=True)


def convert_to_mp3(input_file, output_file, track_num, title, artist, album,
                   duration, total_size, processed_size, queued_audio_seconds,
                   show_disc=True):
	"""Convert an audio file to MP3 using ffmpeg with progress bar and ETA."""
	tmp_path = output_file.with_name(output_file.name + '.ripping')
	try:
		cmd = [
			'ffmpeg', '-i', str(input_file),
			'-codec:a', 'libmp3lame', '-qscale:a', '2',
			'-f', 'mp3',
			'-metadata', f'track={track_num}',
			'-metadata', f'title={title}',
			'-metadata', f'artist={artist}',
		]
		if album:
			cmd += ['-metadata', f'album={album}']
		cmd += ['-progress', 'pipe:1', '-y', str(tmp_path)]

		process = subprocess.Popen(cmd, stdout=subprocess.PIPE,
		                          stderr=subprocess.PIPE, universal_newlines=True)
		last_state = None
		current_time = 0.0
		speed = None

		for line in process.stdout:
			line = line.strip()
			if line.startswith('out_time_ms='):
				try:
					current_time = int(line.split('=')[1]) / 1_000_000
				except (ValueError, IndexError):
					continue
			elif line.startswith('speed='):
				val = line.split('=', 1)[1].rstrip('x').strip()
				try:
					speed = float(val) if val and val != 'N/A' else None
				except ValueError:
					speed = None
			else:
				continue

			if not (duration and duration > 0):
				continue

			progress = min(current_time / duration, 1.0)
			processed_bytes = input_file.stat().st_size * progress
			total_processed = processed_size + processed_bytes
			disc_progress = min(total_processed / total_size, 1.0) if total_size > 0 else 0

			# remaining audio seconds = rest of this track + everything after it
			audio_remaining = max(duration - current_time, 0) + queued_audio_seconds
			if speed and speed > 0:
				eta_sec = audio_remaining / speed
				time_str = f"{int(eta_sec / 60):>2d}m {int(eta_sec % 60):>2d}s"
			else:
				time_str = ""

			state = (int(progress * 100), int(disc_progress * 100), time_str)
			if state != last_state:
				print_progress_bar(progress, disc_progress, time_str, show_disc=show_disc)
				last_state = state

		process.wait()
		if process.returncode == 0:
			os.replace(tmp_path, output_file)
			print_progress_bar(1.0)
			print()
			return True
		else:
			stderr_output = process.stderr.read() if process.stderr else ""
			tmp_path.unlink(missing_ok=True)
			print()
			if stderr_output:
				# show the last few lines of ffmpeg's error output
				err_tail = "\n".join(stderr_output.strip().splitlines()[-5:])
				print(f"     ffmpeg error:\n{err_tail}")
			return False

	except KeyboardInterrupt:
		# kill ffmpeg, drop the half-written tmp, and let the caller exit cleanly
		try:
			process.terminate()
			process.wait(timeout=2)
		except (NameError, subprocess.TimeoutExpired):
			try:
				process.kill()
			except (NameError, ProcessLookupError):
				pass
		tmp_path.unlink(missing_ok=True)
		raise
	except Exception as e:
		tmp_path.unlink(missing_ok=True)
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


def canonical_mp3_name(artist, title):
	"""Match scan.py / serve.py's canonical 'Artist – Title.mp3' form so we
	can dedup against tracks already in /mix."""
	return f"{scan._sanitize_filename(artist)} – {scan._sanitize_filename(title)}.mp3"


def cleanup_ripping_files():
	"""Remove any leftover .ripping temp files from a previous interrupted run"""
	if not MIX_DIR.exists():
		return
	stale = list(MIX_DIR.glob('*.ripping'))
	for f in stale:
		try:
			f.unlink()
		except OSError:
			pass
	if stale:
		print(f"Cleaned up {len(stale)} stale .ripping file(s) from previous run.")


def rip_cd(only_track=None):
	"""Main function to rip CD to MP3 files.
	If only_track is set, only that track number is ripped."""
	print("=" * 60)
	print("💿 mixapps - CD Ripper")
	print("=" * 60)

	# Check for ffmpeg
	if not check_ffmpeg():
		print("\n✗ ffmpeg not found.")
		install_ffmpeg()
	else:
		print("\n✓ ffmpeg found.")

	# Create tracks directory if it doesn't exist
	if not MIX_DIR.exists():
		print(f"\nCreating {MIX_DIR.name} directory...")
		MIX_DIR.mkdir(parents=True, exist_ok=True)

	cleanup_ripping_files()

	# Find CD mount point — poll until one appears (Ctrl-C to quit)
	print("\nSearching for audio CD...")
	mount_point = find_cd_mount()
	if not mount_point:
		print("  Insert an audio CD to begin (Ctrl-C to quit).")
		if platform.system() == "Linux":
			print("  On Linux you may need: sudo mount /dev/cdrom /mnt/cdrom")
		try:
			while not mount_point:
				time.sleep(2)
				mount_point = find_cd_mount()
		except KeyboardInterrupt:
			print("\n\n⚠ Cancelled.")
			sys.exit(130)

	print(f"✓ Found CD at: {mount_point}")

	# Get audio files from CD
	audio_files = get_audio_files(mount_point)

	if not audio_files:
		print("✗ No audio files found on the CD.")
		sys.exit(1)

	print(f"✓ Found {len(audio_files)} audio track(s).")

	if only_track is not None:
		if only_track < 1 or only_track > len(audio_files):
			print(f"✗ Track {only_track} is out of range (CD has {len(audio_files)} tracks).")
			sys.exit(1)
		print(f"\nWill rip only track {only_track} to MP3 format.")
	else:
		print(f"\nThis will copy and convert {len(audio_files)} tracks to MP3 format.")
	print(f"Output directory: {MIX_DIR}")

	# Try MusicBrainz lookup for artist/album/track titles
	if not check_libdiscid():
		print("\n⚠ libdiscid not found — needed for automatic CD metadata lookup.")
		install_libdiscid()

	mb_titles = {}
	album = ""
	artist = ""
	if check_libdiscid():
		print("\nLooking up disc on MusicBrainz...")
		result = lookup_musicbrainz()
		if result:
			artist, album, mb_titles = result
			print(f"✓ Found: {artist} — {album}")
		else:
			print("  No match found.")

	if not artist:
		print("\nEnter the artist name for this album.")
		artist = input("Artist (press Enter for 'Unknown Artist'): ").strip()
		if not artist:
			artist = "Unknown Artist"

	print("\nRipping CD...")
	print("-" * 60)

	# Resolve titles once and partition into skip-vs-rip.
	import re
	planned = []  # list of (idx, audio_file, cleaned_name, will_rip, duration)
	skipped_count = 0
	skipped_size = 0
	print("\nReading track durations...")
	for idx, audio_file in enumerate(audio_files, start=1):
		if only_track is not None and idx != only_track:
			continue
		base_name = sanitize_filename(audio_file.name)
		cleaned_name = re.sub(r'^\d+\s*[-.]?\s*', '', base_name) or base_name
		# prefer MB title — cleaner than the OS-scraped .aiff name
		if idx in mb_titles and mb_titles[idx]:
			cleaned_name = sanitize_filename(mb_titles[idx])

		duration = get_audio_duration(audio_file) or 0

		canonical = canonical_mp3_name(artist, cleaned_name)
		if (MIX_DIR / canonical).exists():
			print(f"Skipping track {idx} of {len(audio_files)}: {cleaned_name} (already in /mix)")
			skipped_count += 1
			skipped_size += audio_file.stat().st_size
			planned.append((idx, audio_file, cleaned_name, False, duration))
		else:
			planned.append((idx, audio_file, cleaned_name, True, duration))

	queued_after = []
	tail = 0.0
	for entry in reversed(planned):
		queued_after.append(tail)
		if entry[3]:  # will_rip
			tail += entry[4]  # duration
	queued_after.reverse()

	success_count = 0
	start_time = time.time()
	total_size = sum(f.stat().st_size for _, f, _, _, _ in planned)
	# pre-seed with skipped bytes so Disc% starts at the right baseline
	processed_size = skipped_size
	padding_width = len(str(len(audio_files)))
	rip_count = sum(1 for _, _, _, will_rip, _ in planned if will_rip)
	show_disc = rip_count > 1

	try:
		for entry_idx, (idx, audio_file, cleaned_name, will_rip, duration) in enumerate(planned):
			if not will_rip:
				continue
			padded_idx = str(idx).zfill(padding_width)
			output_file = MIX_DIR / f"{padded_idx} {cleaned_name}.mp3"

			# Handle duplicate filenames
			counter = 1
			while output_file.exists():
				output_file = MIX_DIR / f"{padded_idx} {cleaned_name}_{counter}.mp3"
				counter += 1

			print(f"Ripping track {idx} of {len(audio_files)}: {cleaned_name}")

			ripped_this_track = False
			if audio_file.suffix.lower() == '.mp3':
				tmp_path = output_file.with_name(output_file.name + '.ripping')
				try:
					shutil.copy2(audio_file, tmp_path)
					os.replace(tmp_path, output_file)
					success_count += 1
					ripped_this_track = True
					print(f"[████████████████████████████████████████] 100%")
					print(f"✓ Ripped: {cleaned_name}")
				except KeyboardInterrupt:
					tmp_path.unlink(missing_ok=True)
					raise
				except Exception as e:
					tmp_path.unlink(missing_ok=True)
					print(f"✗ Error: {e}")
			else:
				if convert_to_mp3(audio_file, output_file, idx, cleaned_name, artist, album,
				                 duration, total_size, processed_size, queued_after[entry_idx],
				                 show_disc=show_disc):
					success_count += 1
					ripped_this_track = True
					print(f"✓ Ripped: {cleaned_name}")
				else:
					print(f"✗ Conversion failed")

			if ripped_this_track:
				scan.rescan(silent=True)

			processed_size += audio_file.stat().st_size
	except KeyboardInterrupt:
		print("\n\n⚠ Interrupted. Cleaning up...")
		cleanup_ripping_files()
		if success_count > 0:
			scan.rescan(silent=True)
		print(f"Ripped {success_count} track(s) before interrupt.")
		sys.exit(130)

	# Calculate total time
	total_time = time.time() - start_time
	total_minutes = int(total_time / 60)
	total_secs = int(total_time % 60)

	print("-" * 60)
	planned_total = len(planned)
	summary = f"\n✓ Successfully ripped {success_count}/{planned_total} tracks in {total_minutes}m {total_secs}s."
	if skipped_count:
		summary += f" ({skipped_count} skipped — already in /mix)"
	print(summary)

	if success_count > 0:
		print(f"\nSaved to: {MIX_DIR}")
		print("\nRun serve.py to test your mixapp.")

	if success_count > 0 or skipped_count == planned_total:
		# Eject the CD
		print("\nEjecting CD...")
		try:
			system = platform.system()
			if system == "Darwin":  # macOS
				subprocess.run(['diskutil', 'eject', str(mount_point)], check=False)
			elif system == "Linux":
				subprocess.run(['eject', str(mount_point)], check=False)
		except Exception as e:
			print(f"Could not auto-eject CD: {e}")
			print("You can manually eject it.")


def main():
	"""Main entry point"""
	only_track = None
	if len(sys.argv) > 1:
		try:
			only_track = int(sys.argv[1])
			if only_track < 1:
				raise ValueError
		except ValueError:
			print(f"Usage: {sys.argv[0]} [track_number]")
			print("  track_number: optional positive integer to rip only that track")
			sys.exit(1)
	rip_cd(only_track=only_track)


if __name__ == "__main__":
	main()