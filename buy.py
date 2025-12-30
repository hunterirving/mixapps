#!/usr/bin/env python3
"""
Search for songs and open purchase links.

Usage:
	./buy.py <search query>
	./buy.py beatles yesterday
	./buy.py "daft punk revolution 909"
"""

import sys
import urllib.parse
import urllib.request
import json
import platform
import webbrowser


def search_itunes(query):
	"""Search iTunes for a song and return results."""
	encoded_query = urllib.parse.quote(query)
	url = f"https://itunes.apple.com/search?term={encoded_query}&media=music&entity=song&limit=10"
	
	try:
		with urllib.request.urlopen(url) as response:
			data = json.loads(response.read().decode())
			return data.get('results', [])
	except Exception as e:
		print(f"Error searching iTunes: {e}")
		return []


def open_itunes_link(itunes_url, track_id):
	"""Open the iTunes purchase link directly in iTunes app on macOS, or song.link on other platforms."""
	import subprocess
	
	# Convert to geo-aware link and add app=itunes parameter to force iTunes Store
	# This prevents opening in Apple Music (streaming) instead of iTunes Store (purchase)
	
	# Replace music.apple.com with geo.itunes.apple.com for better compatibility
	if 'music.apple.com' in itunes_url:
		itunes_url = itunes_url.replace('music.apple.com', 'geo.itunes.apple.com')
	elif 'itunes.apple.com' in itunes_url and 'geo.' not in itunes_url:
		itunes_url = itunes_url.replace('itunes.apple.com', 'geo.itunes.apple.com')
	
	# Add app=itunes parameter to force iTunes Store (not Apple Music)
	if '?' in itunes_url:
		# URL already has parameters, append with &
		if 'app=' not in itunes_url:
			itunes_url += '&app=itunes'
	else:
		# No parameters yet, add with ?
		itunes_url += '?app=itunes'
	
	# Convert https:// to itms:// to open directly in iTunes app
	itunes_url = itunes_url.replace('https://', 'itms://')
	
	# Use macOS 'open' command to bypass browser entirely
	if platform.system() == 'Darwin':  # macOS
		subprocess.run(['open', itunes_url])
		return itunes_url
	else:
		# For non-macOS systems, open song.link page with all platform options
		songlink_url = f"https://song.link/i/{track_id}"
		webbrowser.open(songlink_url)
		return songlink_url


def main():
	"""Main function to run the music search CLI."""
	# Get search query from command line args or prompt user
	if len(sys.argv) > 1:
		query = ' '.join(sys.argv[1:])
	else:
		query = input("Enter song name, artist, or both: ").strip()
	
	if not query:
		print("No search query provided.")
		return
	
	print(f"Searching for: {query}")
	
	# Search iTunes
	results = search_itunes(query)
	
	if not results:
		print("No results found. Try a different search term.")
		return
	
	# Get the best (first) result
	best_track = results[0]
	
	# Extract track info
	artist = best_track.get('artistName', 'Unknown')
	song = best_track.get('trackName', 'Unknown')
	itunes_url = best_track.get('trackViewUrl')
	track_id = best_track.get('trackId')
	
	if not itunes_url or not track_id:
		print("Error: Could not find iTunes URL")
		return
	
	# Open iTunes purchase page (macOS) or song.link (other platforms)
	print(f"Opening: {artist} - {song}")
	if platform.system() == 'Darwin':
		print("(Opening iTunes Store directly)")
	else:
		print("(Opening song.link with all platform options)")
	
	open_itunes_link(itunes_url, track_id)


if __name__ == "__main__":
	try:
		main()
	except KeyboardInterrupt:
		print("\n\nExiting...")
		sys.exit(0)