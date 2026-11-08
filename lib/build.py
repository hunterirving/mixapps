#!/usr/bin/env python3
"""
Creates manifest.json and service-worker.js
(PWA requirements) based on the contents of /mix.
serve.py runs this automatically.
"""

import hashlib
import json
import re
from pathlib import Path

import scan

DEFAULT_NAME = "mixapp"


def shared_album():
	"""The album tag every track in /mix shares, or None"""
	try:
		from mutagen import File as MutagenFile  # type: ignore
	except ImportError:
		return None
	albums = set()
	for path in MIX_DIR.iterdir():
		if path.suffix.lower() not in scan.SUPPORTED_EXTENSIONS:
			continue
		try:
			audio = MutagenFile(path, easy=True)
		except Exception:
			return None
		album = audio.tags.get('album', [None])[0] if audio and audio.tags else None
		if not album:
			return None
		albums.add(album.strip())
	return albums.pop() if len(albums) == 1 else None


def mix_name():
	"""mix/name.txt if present, else the album every track shares, else DEFAULT_NAME"""
	if NAME_FILE.exists():
		name = NAME_FILE.read_text(encoding='utf-8').strip()
		if name:
			return name
	return shared_album() or DEFAULT_NAME


# File paths (no need to edit these)
ROOT_DIR = Path(__file__).parent.parent.absolute()
MIX_DIR = ROOT_DIR / "mix"
NAME_FILE = MIX_DIR / "name.txt"
TRACKS_JSON = ROOT_DIR / "mix" / "tracks.json"
STYLES_CSS = ROOT_DIR / "resources" / "styles.css"
CUSTOM_CSS = ROOT_DIR / "mix" / "custom.css"


def get_background_color(log):
	"""Extract the --background CSS variable, preferring custom.css over styles.css"""
	# Check custom.css first (overrides styles.css)
	for css_file in [CUSTOM_CSS, STYLES_CSS]:
		if not css_file.exists():
			continue
		with open(css_file, 'r', encoding='utf-8') as f:
			content = f.read()
		match = re.search(
			r'--background:\s*([#a-zA-Z0-9(),.\s]+?)\s*;',
			content
		)
		if match:
			color = match.group(1).strip()
			log(f"Found background color in {css_file.name}: {color}")
			return color

	log("Warning: --background not found in any CSS file. Using default color.")
	return "#080a0c"


def build_pwa(silent=False):
	"""Generate manifest.json and service-worker.js from /mix. Returns the mix name."""
	log = (lambda *args: None) if silent else print
	app_name = mix_name()

	# Derived values
	short_name = app_name
	cache_name = app_name
	app_description = f"{app_name}"

	log("Building PWA files...")
	log(f"  Cache name: {cache_name}")

	# Rescan /mix so tracks.json reflects any additions/removals on disk
	# before we snapshot it into the service worker's static file list.
	scan.rescan(silent=True)

	if not TRACKS_JSON.exists():
		log("Error: tracks.json not found.")
		return

	with open(TRACKS_JSON, 'r', encoding='utf-8') as f:
		tracks = json.load(f)

	# Get background color from styles.css
	background_color = get_background_color(log)

	# mix/album_art.jpg overrides the default
	custom_album_art = ROOT_DIR / "mix" / "album_art.jpg"
	album_art_file = custom_album_art if custom_album_art.exists() else ROOT_DIR / "resources" / "album_art.jpg"
	album_art_path = "mix/album_art.jpg" if custom_album_art.exists() else "resources/album_art.jpg"
	# append a content hash so the URL changes when the image changes
	if album_art_file.exists():
		art_hash = hashlib.md5(album_art_file.read_bytes()).hexdigest()[:8]
		album_art_path = f"{album_art_path}?v={art_hash}"
	log(f"  Album art: {album_art_path}")

	# mix/icon.png overrides the default
	custom_icon = ROOT_DIR / "mix" / "icon.png"
	icon_file = custom_icon if custom_icon.exists() else ROOT_DIR / "resources" / "icon.png"
	icon_path = "mix/icon.png" if custom_icon.exists() else "resources/icon.png"
	# append a content hash so the URL changes when the image changes
	if icon_file.exists():
		icon_hash = hashlib.md5(icon_file.read_bytes()).hexdigest()[:8]
		icon_path = f"{icon_path}?v={icon_hash}"
	log(f"  Icon: {icon_path}")

	# Generate manifest.json
	manifest = {
		"name": app_name,
		"short_name": short_name,
		"description": app_description,
		"start_url": "./",
		"scope": "./",
		"display": "standalone",
		"background_color": background_color,
		"theme_color": background_color,
		"cache_name": cache_name,  # Custom field for script.js to use
		"album_art": album_art_path,  # Custom field for script.js to use
		"icons": [
			{
				"src": icon_path,
				"sizes": "640x640",
				"type": "image/png",
				"purpose": "any maskable"
			}
		]
	}

	with open(ROOT_DIR / "manifest.json", 'w', encoding='utf-8') as f:
		json.dump(manifest, f, indent=2)
	log("✓ Generated manifest.json")

	# Build static files list for service worker
	static_files = [
		"./",
		"index.html",
		"manifest.json",
		"resources/styles.css",
		"resources/script.js",
		"mix/tracks.json",
		icon_path,
		album_art_path,
		"resources/play.svg",
		"resources/pause.svg",
		"resources/prev.svg",
		"resources/next.svg",
		"resources/repeat.svg",
		"resources/fonts/Basteleur/Basteleur-Moonlight.woff2",
	]

	AUDIO_EXTS = {".mp3", ".m4a", ".ogg", ".flac", ".wav"}
	# album_art.jpg and icon.png added explicitly above with a hash; skip to avoid a bare dupe
	SKIP_NAMES = {"tracks.json", "readme.md", "album_art.jpg", "icon.png", "name.txt"}
	for path in sorted((ROOT_DIR / "mix").iterdir()):
		if not path.is_file():
			continue
		if path.name in SKIP_NAMES:
			continue
		if path.suffix.lower() in AUDIO_EXTS:
			continue
		static_files.append(f"mix/{path.name}")

	static_files_js = json.dumps(static_files)
	audio_pattern = "|".join(sorted(ext[1:] for ext in AUDIO_EXTS))

	# Generate service-worker.js
	service_worker_content = f'''// Auto-generated service worker for {app_name} PWA
const CACHE_NAME = '{cache_name}';

// Get the base path from the service worker location
const getBasePath = () => {{
	const swPath = self.location.pathname;
	return swPath.substring(0, swPath.lastIndexOf('/') + 1);
}};

const basePath = getBasePath();

// Static files to cache on install
const STATIC_FILES = {static_files_js};
const AUDIO_FILE = /\\.({audio_pattern})$/i;

// Install event - cache static resources only if not already cached.
// This makes installs immutable: once a file is in the cache, redeploys
// will not overwrite it, so the app stays frozen at its first-installed version.
// Audio files will be cached by the main app's blob preloading system.
self.addEventListener('install', (event) => {{
	console.log('Service Worker installing...', 'Base path:', basePath);
	self.skipWaiting();
	event.waitUntil(
		caches.open(CACHE_NAME).then(cache => {{
			const absoluteUrls = STATIC_FILES.map(url => {{
				if (url === './') return new URL(basePath, self.location.href).href;
				return new URL(url, new URL(basePath, self.location.href)).href;
			}});

			return Promise.allSettled(
				absoluteUrls.map(url =>
					cache.match(url).then(existing => {{
						if (existing) {{
							console.log('• Already cached, skipping:', url);
							return;
						}}
						return fetch(url, {{ cache: 'no-cache' }})
							.then(response => {{
								if (!response.ok) {{
									throw new Error(`HTTP error! status: ${{response.status}}`);
								}}
								return cache.put(url, response);
							}})
							.then(() => console.log('✓ Cached:', url))
							.catch(err => {{
								console.error('✗ Failed to cache:', url, err);
								throw err;
							}});
					}})
				)
			).then(results => {{
				const failed = results.filter(r => r.status === 'rejected');
				console.log(`Install complete: ${{results.length - failed.length}}/${{results.length}} ok`);
			}});
		}}).catch(error => {{
			console.error('Service Worker installation failed:', error);
		}})
	);
}});

self.addEventListener('activate', (event) => {{
	event.waitUntil(self.clients.claim());
}});

// Network fetch capped with a timeout. A mixapp installed off the LAN points
// at a private-IP origin that's usually gone by launch time; without a cap an
// uncached request hangs on a TCP timeout and stalls startup (black→white
// screen). Aborting fast turns that hang into an ordinary cache-miss failure.
const fetchWithTimeout = (request, ms = 2000) => {{
	const controller = new AbortController();
	const timer = setTimeout(() => controller.abort(), ms);
	return fetch(request, {{ signal: controller.signal }})
		.finally(() => clearTimeout(timer));
}};

// Fetch event - cache first, network fallback
self.addEventListener('fetch', (event) => {{
	// Ignore non-http(s) requests like blob: URLs, data: URLs, chrome-extension:, etc.
	if (!event.request.url.startsWith('http')) {{
		return;
	}}

	event.respondWith(
		caches.match(event.request)
			.then((cachedResponse) => {{
				if (cachedResponse) {{
					console.log('✓ Serving from cache:', event.request.url);
					return cachedResponse;
				}}

				// Navigation that missed the exact cache key: serve the cached
				// app shell so the document always renders from cache, online
				// or off, even if the launch URL doesn't byte-match a key.
				if (event.request.mode === 'navigate') {{
					const shellUrl = new URL(basePath, self.location.href).href;
					return caches.match(shellUrl)
						.then(shell => shell || caches.match('index.html'))
						.then(shell => shell || fetchWithTimeout(event.request));
				}}

				// Not in cache - try network (time-boxed; see fetchWithTimeout)
				console.log('⟳ Fetching from network:', event.request.url);
				return fetchWithTimeout(event.request)
					.then((networkResponse) => {{
						// Check if valid response
						if (!networkResponse || networkResponse.status !== 200 || networkResponse.type === 'error') {{
							return networkResponse;
						}}

						if (AUDIO_FILE.test(new URL(event.request.url).pathname)) {{
							return networkResponse;
						}}

						// Clone and cache for future offline use
						const responseToCache = networkResponse.clone();
						caches.open(CACHE_NAME)
							.then((cache) => {{
								cache.put(event.request, responseToCache);
								console.log('✓ Cached from network:', event.request.url);
							}})
							.catch(err => console.error('Failed to cache:', err));

						return networkResponse;
					}})
					.catch((error) => {{
						console.error('✗ Network fetch failed for:', event.request.url, error);
						throw error;
					}});
			}})
	);
}});
'''

	with open(ROOT_DIR / "service-worker.js", 'w', encoding='utf-8') as f:
		f.write(service_worker_content)
	log("✓ Generated service-worker.js")
	log()
	log("PWA build complete!")
	return app_name


if __name__ == "__main__":
	scan.bootstrap(__file__)
	build_pwa()
