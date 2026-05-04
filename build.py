#!/usr/bin/env python3
"""
Creates manifest.json and service-worker.js
(PWA requirements) based on the contents of tracks.json
"""

import json
import re
from pathlib import Path

def get_configuration():
	"""Prompt user for configuration values"""
	print("=" * 60)
	print("PWA Configuration")
	print("=" * 60)
	print()

	# Get app name
	app_name = input("Enter a name for your mixapp: ").strip()
	if not app_name:
		print("Error: App name is required")
		exit(1)

	# Get base path with smart default
	default_path = app_name.lower().replace(" ", "_")
	print()
	print(f"Enter the deployment path (or press Return/Enter for default)")
	print(f"Default: /{default_path}/")
	base_path_input = input("Path: ").strip()

	if base_path_input:
		# User provided a path - ensure it has leading/trailing slashes
		base_path = base_path_input
		if not base_path.startswith("/"):
			base_path = "/" + base_path
		if not base_path.endswith("/"):
			base_path = base_path + "/"
	else:
		# Use default
		base_path = f"/{default_path}/"
		print(f"Using default path: {base_path}")

	print()
	print(f"Configuration:")
	print(f"  App Name: {app_name}")
	print(f"  Base Path: {base_path}")
	print()

	return app_name, base_path

# File paths (no need to edit these)
SCRIPT_DIR = Path(__file__).parent.absolute()
TRACKS_JSON = SCRIPT_DIR / "mix" / "tracks.json"
STYLES_CSS = SCRIPT_DIR / "resources" / "styles.css"
CUSTOM_CSS = SCRIPT_DIR / "mix" / "custom.css"


def get_background_color():
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
			print(f"Found background color in {css_file.name}: {color}")
			return color

	print("Warning: --background not found in any CSS file. Using default color.")
	return "#080a0c"


def build_pwa(app_name=None, base_path=None):
	"""Generate manifest.json and service-worker.js based on tracks.json

	Args:
		app_name: Name of the app. If None, will be prompted via get_configuration()
		base_path: Base path for the app. If None, will be prompted via get_configuration()
	"""
	# Get configuration if not provided
	if app_name is None or base_path is None:
		app_name, base_path = get_configuration()

	# Derived values
	short_name = app_name
	cache_name = app_name
	app_description = f"{app_name}"

	print("Building PWA files...")
	print(f"  Cache name: {cache_name}")

	# Load tracks.json
	if not TRACKS_JSON.exists():
		print("Error: tracks.json not found. Run scan.py first.")
		return

	with open(TRACKS_JSON, 'r', encoding='utf-8') as f:
		tracks = json.load(f)

	# Get background color from styles.css
	background_color = get_background_color()

	# Generate manifest.json
	manifest = {
		"id": base_path,
		"name": app_name,
		"short_name": short_name,
		"description": app_description,
		"start_url": base_path,
		"scope": base_path,
		"display": "standalone",
		"background_color": background_color,
		"theme_color": background_color,
		"cache_name": cache_name,  # Custom field for script.js to use
		"icons": [
			{
				"src": f"{base_path}resources/icon.png",
				"sizes": "640x640",
				"type": "image/png",
				"purpose": "any maskable"
			}
		]
	}

	with open(SCRIPT_DIR / "manifest.json", 'w', encoding='utf-8') as f:
		json.dump(manifest, f, indent=2)
	print("✓ Generated manifest.json")

	# Build static files list for service worker
	static_files = [
		"./",
		"index.html",
		"manifest.json",
		"resources/styles.css",
		"resources/script.js",
		"mix/tracks.json",
		"resources/icon.png",
		"resources/album_art.jpg",
		"resources/play.svg",
		"resources/pause.svg",
		"resources/prev.svg",
		"resources/next.svg",
		"resources/repeat.svg",
		"resources/fonts/Basteleur/Basteleur-Moonlight.woff2",
	]

	AUDIO_EXTS = {".mp3", ".m4a", ".ogg", ".flac", ".wav"}
	SKIP_NAMES = {"tracks.json", "readme.md"}
	for path in sorted((SCRIPT_DIR / "mix").iterdir()):
		if not path.is_file():
			continue
		if path.name in SKIP_NAMES:
			continue
		if path.suffix.lower() in AUDIO_EXTS:
			continue
		static_files.append(f"mix/{path.name}")

	static_files_js = json.dumps(static_files)

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

// Install event - cache static resources only if not already cached.
// This makes installs immutable: once a file is in the cache, redeploys
// will not overwrite it, so the app stays frozen at its first-installed version.
// Audio files will be cached by the main app's blob preloading system.
self.addEventListener('install', (event) => {{
	console.log('Service Worker installing...', 'Base path:', basePath);
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

				// Not in cache - try network
				console.log('⟳ Fetching from network:', event.request.url);
				return fetch(event.request)
					.then((networkResponse) => {{
						// Check if valid response
						if (!networkResponse || networkResponse.status !== 200 || networkResponse.type === 'error') {{
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

	with open(SCRIPT_DIR / "service-worker.js", 'w', encoding='utf-8') as f:
		f.write(service_worker_content)
	print("✓ Generated service-worker.js")
	print()
	print("PWA build complete!")


if __name__ == "__main__":
	# When run directly, get configuration and build PWA files
	app_name, base_path = get_configuration()
	build_pwa(app_name, base_path)
