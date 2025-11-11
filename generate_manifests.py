#!/usr/bin/env python3
"""
Creates manifest.json, resource-manifest.json, and service-worker.js
based on the contents of tracks.json
"""

import json
import re
from pathlib import Path

def get_configuration(localhost=False):
	"""Prompt user for configuration values

	Args:
		localhost: If True, assumes root path and only asks for app name.
		           This enables PWA installation on localhost (iOS 18+).
	"""
	print("=" * 60)
	print("PWA Configuration")
	print("=" * 60)
	print()

	# Get app name
	if localhost:
		app_name = input("Enter a name for your mixapp (or press Return/Enter for 'vibe capsule'): ").strip()
		if not app_name:
			app_name = "vibe capsule"
			print(f"Using default: {app_name}")
	else:
		app_name = input("Enter a name for your mixapp: ").strip()
		if not app_name:
			print("Error: App name is required")
			exit(1)

	# For localhost mode, use root path
	if localhost:
		base_path = "/"
		print()
		print("Localhost mode: Using root path for PWA installation")
	else:
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
TRACKS_JSON = SCRIPT_DIR / "tracks" / "tracks.json"
STYLES_CSS = SCRIPT_DIR / "styles.css"


def get_background_color():
	"""Extract the --background CSS variable from styles.css"""
	if not STYLES_CSS.exists():
		print("Warning: styles.css not found. Using default color.")
		return "#080a0c"

	with open(STYLES_CSS, 'r', encoding='utf-8') as f:
		content = f.read()

	# Look for --background: <color>; pattern
	match = re.search(
		r'--background:\s*([#a-zA-Z0-9(),.\s]+?)\s*;',
		content
	)
	if match:
		color = match.group(1).strip()
		print(f"Found background color in styles.css: {color}")
		return color

	print("Warning: --background not found in styles.css. Using default color.")
	return "#080a0c"


def generate_pwa_manifests(app_name=None, base_path=None):
	"""Generate PWA manifest files based on tracks.json

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
	app_description = f"{app_name} · vibe capsule"

	print("Generating PWA manifests...")

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
				"src": "resources/icon.png",
				"sizes": "640x640",
				"type": "image/png",
				"purpose": "any maskable"
			}
		]
	}

	with open(SCRIPT_DIR / "manifest.json", 'w', encoding='utf-8') as f:
		json.dump(manifest, f, indent=2)
	print("✓ Generated manifest.json")

	# Generate resource-manifest.json
	resource_manifest = {
		"static_files": [
			"./",
			"index.html",
			"styles.css",
			"script.js",
			"tracks/tracks.json",
			"resources/icon.png",
			"resources/play.png",
			"resources/pause.png",
			"resources/prev.png",
			"resources/next.png",
			"resources/album_art.jpg"
		],
		"tracks": [f"tracks/{track['filename']}" for track in tracks]
	}

	with open(SCRIPT_DIR / "resource-manifest.json", 'w', encoding='utf-8') as f:
		json.dump(resource_manifest, f, indent=2)
	print("✓ Generated resource-manifest.json")

	# Generate service-worker.js
	static_files = resource_manifest["static_files"]
	service_worker_content = f'''// Auto-generated service worker for {app_name} PWA
const CACHE_NAME = '{cache_name}';
const staticFilesToCache = {json.dumps(static_files, indent=2)};

// Get the base path from the service worker location
const getBasePath = () => {{
	const swPath = self.location.pathname;
	return swPath.substring(0, swPath.lastIndexOf('/') + 1);
}};

const basePath = getBasePath();

// Install event - cache only static resources (not MP3s)
// MP3s will be cached by the main app's blob preloading system
self.addEventListener('install', (event) => {{
	console.log('Service Worker installing...', 'Base path:', basePath);
	event.waitUntil(
		caches.open(CACHE_NAME)
			.then((cache) => {{
				console.log('Opened cache');
				// Make URLs absolute relative to service worker location
				const absoluteUrls = staticFilesToCache.map(url => {{
					if (url === './') return basePath;
					return new URL(url, basePath + 'index.html').href;
				}});
				console.log('Caching', absoluteUrls.length, 'static resources');
				console.log('URLs to cache:', absoluteUrls);

				// Cache files individually with better error handling
				// Using Promise.allSettled to continue even if some fail
				return Promise.allSettled(
					absoluteUrls.map(url =>
						fetch(url)
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
							}})
					)
				).then(results => {{
					const failed = results.filter(r => r.status === 'rejected');
					const succeeded = results.filter(r => r.status === 'fulfilled');
					console.log(`Cached ${{succeeded.length}}/${{results.length}} static resources`);
					if (failed.length > 0) {{
						console.warn(`Failed to cache ${{failed.length}} resources`);
					}}
				}});
			}})
			.then(() => {{
				console.log('Service Worker installation complete');
				return self.skipWaiting();
			}})
			.catch(error => {{
				console.error('Service Worker installation failed:', error);
			}})
	);
}});

// Activate event - clean up old caches
self.addEventListener('activate', (event) => {{
	console.log('Service Worker activating...');
	event.waitUntil(
		caches.keys().then((cacheNames) => {{
			return Promise.all(
				cacheNames.map((cacheName) => {{
					if (cacheName !== CACHE_NAME) {{
						console.log('Deleting old cache:', cacheName);
						return caches.delete(cacheName);
					}}
				}})
			);
		}}).then(() => self.clients.claim())
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
	print("PWA manifests generated successfully!")


if __name__ == "__main__":
	# When run directly, get configuration and generate manifests
	app_name, base_path = get_configuration()
	generate_pwa_manifests(app_name, base_path)
