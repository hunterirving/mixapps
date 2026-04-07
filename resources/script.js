// Register service worker for PWA functionality (skip on localhost to avoid caching during development)
if ('serviceWorker' in navigator && location.hostname !== 'localhost' && location.hostname !== '127.0.0.1') {
	window.addEventListener('load', () => {
		navigator.serviceWorker.register('service-worker.js')
			.then(registration => {
				console.log('Service Worker registered successfully:', registration.scope);
			})
			.catch(error => {
				console.log('Service Worker registration failed:', error);
			});
	});
} else if ('serviceWorker' in navigator && (location.hostname === 'localhost' || location.hostname === '127.0.0.1')) {
	// On localhost, unregister any existing service worker and clear caches
	navigator.serviceWorker.getRegistrations().then(registrations => {
		registrations.forEach(r => r.unregister());
	});
	caches.keys().then(keys => {
		keys.forEach(k => caches.delete(k));
	});
}

const playPauseBtn = document.getElementById('playPause');
const prevBtn = document.getElementById('prev');
const nextBtn = document.getElementById('next');
const playlist = document.getElementById('playlist');
const currentTrackDisplay = document.getElementById('currentTrack');
const progressBar = document.getElementById('progressBar');
const progressContainer = document.getElementById('progressContainer');
const audio = document.getElementById('audioPlayer');
audio.controls = true; // Enable controls for iOS media session

const shuffle = false;

function shuffleArray(array) {
	const shuffled = [...array];
	for (let i = shuffled.length - 1; i > 0; i--) {
		const j = Math.floor(Math.random() * (i + 1));
		[shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
	}
	return shuffled;
}

let currentTrackIndex = 0;
let isPlaying = false;
let progressInterval;
let playerReady = false;
let tracks = [];
let animationFrameId = null;
let prePlaySeekTime = 0;
let preloadedAudio = {}; // Cache for preloaded audio elements
let currentPreloadIndex = 0;
let priorityPreloadQueue = []; // Tracks requested by user that need priority preloading
let isPreloadingPriority = false;
let totalBytesLoaded = 0; // Track total filesize of all preloaded tracks
let cachedTracks = new Set(); // Track which tracks are cached for offline use
let CACHE_NAME = 'my-mixapp'; // Default fallback
const staticFiles = [
	'./',
	'index.html',
	'resources/styles.css',
	'resources/script.js',
	'mix/tracks.json',
	'resources/icon.png',
	'resources/play.svg',
	'resources/pause.svg',
	'resources/prev.svg',
	'resources/next.svg',
	'resources/repeat.svg',
];

// Retry fetch with exponential backoff
async function fetchWithRetry(url, maxRetries = 4, baseDelay = 2000) {
	for (let attempt = 0; attempt <= maxRetries; attempt++) {
		try {
			const response = await fetch(url);
			if (!response.ok) {
				throw new Error(`HTTP error! status: ${response.status}`);
			}
			return response;
		} catch (error) {
			if (attempt === maxRetries) throw error;
			const delay = baseDelay * Math.pow(2, attempt);
			console.warn(`Fetch failed for ${url}, retrying in ${delay}ms (attempt ${attempt + 1}/${maxRetries})...`);
			await new Promise(resolve => setTimeout(resolve, delay));
		}
	}
}

// Load cache name from manifest.json first, then load tracks
fetch('manifest.json')
	.then(response => {
		if (!response.ok) return null;
		return response.json();
	})
	.catch(() => null)
	.then(manifest => {
		if (manifest) {
			CACHE_NAME = manifest.cache_name || manifest.name || CACHE_NAME;
			console.log('Using cache name:', CACHE_NAME);

			if (manifest.name) {
				document.title = manifest.name;
			}
		}

		// Probe for optional files and add them to staticFiles
		const optionalFiles = ['mix/album_art.jpg', 'mix/custom.css', 'mix/custom.js'];
		return Promise.all([
			...optionalFiles.map(f =>
				fetch(f, { method: 'HEAD' })
					.then(r => { if (r.ok) staticFiles.push(f); })
					.catch(() => {})
			),
			fetch('mix/tracks.json')
				.then(r => {
					if (!r.ok) throw new Error('tracks.json not found');
					return r.json();
				})
				.catch(() => {
					// Offline fallback: try loading from cache directly
					return caches.open(CACHE_NAME)
						.then(cache => cache.match('mix/tracks.json'))
						.then(r => r ? r.json() : Promise.reject('tracks.json not in cache'));
				})
		]);
	})
	.then((results) => {
		const data = results[results.length - 1];

		tracks = shuffle ? shuffleArray(data) : data;
		if (tracks.length > 0) {
			playerReady = true;
			updateCurrentTrackDisplay(`Ready to play: ${tracks[0].artist} – ${tracks[0].title}`);
			// Check which tracks are already cached before rendering
			return checkCachedTracks().then(() => {
				renderPlaylist();
				// Verify all static files are cached, then start caching tracks
				return verifyStaticCache().then(() => {
					startPreloadingTracks();
				});
			});
		} else {
			updateCurrentTrackDisplay('No tracks found');
		}
	})
	.catch(error => {
		console.error('Error loading tracks:', error);
		updateCurrentTrackDisplay('Unable to load tracks. Please check your connection.');
	});

// Audio event listeners
audio.addEventListener('play', () => {
	isPlaying = true;
	updatePlayPauseButton();
	startProgressBar();
	const track = tracks[currentTrackIndex];
	const trackText = `${track.artist} – ${track.title}`;

	// Always update display to ensure we remove "Ready to play:" prefix
	const currentText = currentTrackDisplay.querySelector('span')?.textContent || '';

	// Check if it's a different track (not just play/pause of same track)
	const isNewTrack = !currentText.includes(trackText);
	const hasReadyToPlay = currentText.includes('Ready to play:');

	if (isNewTrack || hasReadyToPlay) {
		updateCurrentTrackDisplay(trackText);
	} else {
		// Same track, just resume the marquee
		resumeMarquee();
	}

	// Update media session metadata
	if ('mediaSession' in navigator) {
		// Convert relative path to absolute URL for media session
		// Use document.baseURI to correctly resolve paths in subdirectories
		const albumArtUrl = new URL('mix/album_art.jpg', document.baseURI).href;
		navigator.mediaSession.metadata = new MediaMetadata({
			title: track.title,
			artist: track.artist,
			artwork: [
				{ src: albumArtUrl, sizes: '860x860', type: 'image/jpeg' },
				{ src: albumArtUrl, sizes: '512x512', type: 'image/jpeg' },
				{ src: albumArtUrl, sizes: '256x256', type: 'image/jpeg' },
				{ src: albumArtUrl, sizes: '128x128', type: 'image/jpeg' }
			]
		});

		// Set action handlers after playback starts (required for iOS)
		// Explicitly set seek handlers to null so iOS shows next/prev instead
		navigator.mediaSession.setActionHandler('play', () => {
			if (playerReady && !isPlaying) {
				togglePlayPause();
			}
		});

		navigator.mediaSession.setActionHandler('pause', () => {
			if (playerReady && isPlaying) {
				togglePlayPause();
			}
		});

		navigator.mediaSession.setActionHandler('previoustrack', () => {
			if (playerReady) {
				prevTrack();
			}
		});

		navigator.mediaSession.setActionHandler('nexttrack', () => {
			if (playerReady) {
				nextTrack();
			}
		});

		// Explicitly set seek handlers to null to show track controls instead
		navigator.mediaSession.setActionHandler('seekbackward', null);
		navigator.mediaSession.setActionHandler('seekforward', null);
	}
});

audio.addEventListener('pause', () => {
	isPlaying = false;
	updatePlayPauseButton();
	stopProgressBar();
	pauseMarquee();
});

audio.addEventListener('ended', () => {
	if (tracks[currentTrackIndex].looping) {
		audio.currentTime = 0;
		audio.play();
	} else {
		nextTrack();
	}
});

audio.addEventListener('error', (e) => {
	console.error('Audio error:', e);
	updateCurrentTrackDisplay(`Error loading: ${tracks[currentTrackIndex].filename}`);
	// Try next track after a brief delay
	setTimeout(() => nextTrack(), 1000);
});

audio.addEventListener('loadedmetadata', () => {
	resetProgressBar();
});

function renderPlaylist() {
	playlist.innerHTML = '';
	const currentDisplayText = currentTrackDisplay.textContent;
	const isInitialized = currentDisplayText !== 'No track playing';

	tracks.forEach((track, index) => {
		const item = document.createElement('div');
		item.classList.add('playlist-item');

		const contentDiv = document.createElement('div');
		contentDiv.classList.add('playlist-item-content');

		const titleDiv = document.createElement('div');
		titleDiv.classList.add('playlist-item-title');
		if (isInitialized && index === currentTrackIndex) {
			titleDiv.classList.add('current');
		}
		titleDiv.textContent = track.title;

		const artistDiv = document.createElement('div');
		artistDiv.classList.add('playlist-item-artist');
		if (isInitialized && index === currentTrackIndex) {
			artistDiv.classList.add('current');
		}
		artistDiv.textContent = track.artist;

		// Set cached status for visual indication
		const isCached = cachedTracks.has(track.filename);
		if (!isCached) {
			contentDiv.classList.add('uncached');
		}

		contentDiv.appendChild(titleDiv);
		contentDiv.appendChild(artistDiv);

		const loopIcon = document.createElement('span');
		loopIcon.style.width = '1.18em';
		loopIcon.style.height = '1.18em';
		loopIcon.style.display = (track.looping || false) ? 'inline-block' : 'none';
		loopIcon.style.color = 'var(--text)';
		fetch('resources/repeat.svg')
			.then(r => r.text())
			.then(svgText => {
				loopIcon.innerHTML = svgText;
				const svg = loopIcon.querySelector('svg');
				if (svg) {
					svg.style.width = '1.18em';
					svg.style.height = '1.18em';
				}
			});

		item.appendChild(contentDiv);
		item.appendChild(loopIcon);
		item.addEventListener('click', () => toggleLooping(index));
		playlist.appendChild(item);
	});
}

function toggleLooping(index) {
	if (!playerReady) return;
	if (index === currentTrackIndex) {
		if (!isPlaying && currentTrackDisplay.textContent.includes('Ready to play')) {
			audio.play().catch(err => {
				console.error('Failed to play audio:', err);
			});
			isPlaying = true;
			updatePlayPauseButton();
			return;
		}
		// Toggle looping
		tracks[index].looping = !(tracks[index].looping || false);
		renderPlaylist();
	} else {
		playTrack(index);
	}
}

function playTrack(index) {
	console.log(`playTrack called with index: ${index}`);
	if (!playerReady) {
		console.log('Player not ready');
		return;
	}
	// Clear looping from all tracks except the new one if it was already looping
	const wasLooping = tracks[index].looping || false;
	tracks.forEach(track => track.looping = false);
	if (wasLooping) {
		tracks[index].looping = true;
	}

	currentTrackIndex = index;
	const track = tracks[currentTrackIndex];
	console.log(`Attempting to play: ${track.artist} – ${track.title}`);
	console.log(`Filename: ${track.filename}`);
	console.log(`Is in preloadedAudio: ${!!preloadedAudio[track.filename]}`);

	// Use preloaded blob if available, otherwise load from server
	if (preloadedAudio[track.filename]) {
		const blobUrl = preloadedAudio[track.filename].blobUrl;
		console.log(`Playing from preloaded blob: ${track.filename}`);
		console.log(`Blob URL: ${blobUrl}`);
		audio.src = blobUrl;
	} else {
		console.log(`Track not preloaded, loading: ${track.filename}`);
		audio.src = `mix/${track.filename}`;
		// Request priority preloading for this track
		requestPriorityPreload(track.filename);
	}

	console.log(`Audio src set to: ${audio.src}`);

	// For iOS PWA: We need to call load() and play() synchronously
	// Reset any previous state first
	try {
		audio.pause();
		audio.currentTime = 0;
	} catch (e) {
		// Ignore errors from resetting
	}

	// Load the audio to ensure it's ready (important for iOS PWA)
	audio.load();

	// Small delay to let load() initialize, then play
	// This needs to be synchronous enough that iOS considers it part of the user gesture
	const playAttempt = audio.play();

	if (playAttempt !== undefined) {
		playAttempt.then(() => {
			console.log('Audio playback started successfully');
			isPlaying = true;
			updatePlayPauseButton();
		}).catch(err => {
			console.error('Failed to play audio:', err);
			console.error('Error name:', err.name);
			console.error('Error message:', err.message);
			isPlaying = false;
			updatePlayPauseButton();
			updateCurrentTrackDisplay(`Error playing: ${track.title}`);
		});
	}

	// Optimistically set playing state
	isPlaying = true;
	updatePlayPauseButton();
	renderPlaylist();
}

function updateCurrentTrackDisplay(text) {
	currentTrackDisplay.innerHTML = `<span>${text}</span>`;
	// Initialize marquee effect after a brief delay to ensure DOM is updated
	setTimeout(() => setupMarquee(), 50);
}

// Marquee state
let marqueeAnimating = false;
let marqueePaused = false;
let marqueeTimeoutId = null;
let marqueeOriginalText = '';
let marqueeHalfWidth = 0;
let marqueeRafId = null;
let marqueeStartTime = 0;
let marqueeElapsedBeforePause = 0;
const marqueeSpeed = 50; // pixels per second

function setupMarquee() {
	const container = currentTrackDisplay;
	const textSpan = container.querySelector('span');

	if (!textSpan) return;

	// Clear any existing animation
	if (marqueeTimeoutId) {
		clearTimeout(marqueeTimeoutId);
		marqueeTimeoutId = null;
	}
	if (marqueeRafId) {
		cancelAnimationFrame(marqueeRafId);
		marqueeRafId = null;
	}
	marqueeAnimating = false;
	marqueePaused = false;
	marqueeElapsedBeforePause = 0;

	// Reset styles
	textSpan.style.transform = 'translateX(0)';
	textSpan.style.animation = 'none';
	container.classList.remove('no-overflow');

	// Store original text
	marqueeOriginalText = textSpan.textContent;

	// Force reflow
	void textSpan.offsetWidth;

	// Check if text overflows
	const containerWidth = container.offsetWidth - 30; // Account for padding
	const textWidth = textSpan.scrollWidth;
	const overflows = textWidth > containerWidth;

	if (!overflows) {
		// No overflow - show ellipsis behavior
		container.classList.add('no-overflow');
		container.classList.remove('marquee-active');
		return;
	}

	// Text overflows - setup marquee
	marqueeAnimating = true;
	container.classList.add('marquee-active');

	// Add spacing and duplicate text for seamless loop
	// Using non-breaking spaces (\u00A0) so they don't collapse in HTML
	const spacing = '\u00A0\u00A0\u00A0\u00A0\u00A0\u00A0\u00A0\u00A0\u00A0\u00A0\u00A0\u00A0'; // 12 non-breaking spaces
	textSpan.textContent = marqueeOriginalText + spacing + marqueeOriginalText + spacing;

	// Calculate animation parameters
	const fullWidth = textSpan.scrollWidth;
	marqueeHalfWidth = fullWidth / 2;

	// Start animation after a brief delay (only if not paused)
	if (!marqueePaused) {
		marqueeTimeoutId = setTimeout(() => {
			if (marqueePaused) return;
			marqueeStartTime = performance.now();
			marqueeElapsedBeforePause = 0;
			marqueeRafId = requestAnimationFrame(marqueeStep);
		}, 1000); // Initial delay before starting scroll
	}
}

function marqueeStep(now) {
	if (!marqueeAnimating || marqueePaused) return;

	const elapsed = marqueeElapsedBeforePause + (now - marqueeStartTime);
	const totalDistance = elapsed * marqueeSpeed / 1000;
	// Modulo by one segment width for seamless wrapping — no loop boundary
	const offset = totalDistance % marqueeHalfWidth;

	const textSpan = currentTrackDisplay.querySelector('span');
	if (textSpan) {
		textSpan.style.transform = `translateX(-${offset}px)`;
	}

	marqueeRafId = requestAnimationFrame(marqueeStep);
}

function pauseMarquee() {
	marqueePaused = true;
	if (!marqueeAnimating) return;

	// Accumulate elapsed time before this pause
	marqueeElapsedBeforePause += performance.now() - marqueeStartTime;

	if (marqueeRafId) {
		cancelAnimationFrame(marqueeRafId);
		marqueeRafId = null;
	}

	// Clear any pending timeout (for initial delay)
	if (marqueeTimeoutId) {
		clearTimeout(marqueeTimeoutId);
		marqueeTimeoutId = null;
	}
}

function resumeMarquee() {
	if (!marqueeAnimating) return;
	marqueePaused = false;

	const textSpan = currentTrackDisplay.querySelector('span');
	if (!textSpan) return;

	// Resume from where we left off
	marqueeStartTime = performance.now();
	marqueeRafId = requestAnimationFrame(marqueeStep);
}

// Add window resize listener to recalculate marquee
window.addEventListener('resize', () => {
	if (marqueeOriginalText) {
		// Store the paused state before recalculating
		const wasPaused = marqueePaused;

		// Restore original text before recalculating
		const textSpan = currentTrackDisplay.querySelector('span');
		if (textSpan) {
			textSpan.textContent = marqueeOriginalText;
		}

		setupMarquee();

		// Restore paused state after recalculation
		if (wasPaused) {
			marqueePaused = true;
		}
	}
});

function togglePlayPause() {
	if (!playerReady) return;
	if (isPlaying) {
		audio.pause();
		isPlaying = false;
	} else {
		// If no track is loaded, load the first one
		if (!audio.src || audio.src === '') {
			playTrack(currentTrackIndex);
		} else {
			audio.play().catch(err => {
				console.error('Failed to play audio:', err);
				const track = tracks[currentTrackIndex];
				updateCurrentTrackDisplay(`Error playing: ${track.title}`);
			});
			isPlaying = true;
		}
	}
	updatePlayPauseButton();
}

function updatePlayPauseButton() {
	playPauseBtn.classList.toggle('pause', isPlaying);
}

function nextTrack() {
	if (!playerReady) return;
	currentTrackIndex = (currentTrackIndex + 1) % tracks.length;
	playTrack(currentTrackIndex);
}

function prevTrack() {
	if (!playerReady) return;
	if (audio.currentTime <= 3) {
		currentTrackIndex = (currentTrackIndex - 1 + tracks.length) % tracks.length;
		playTrack(currentTrackIndex);
	} else {
		audio.currentTime = 0;
	}
}

function startProgressBar() {
	stopProgressBar();

	function animate() {
		updateProgressBar();
		animationFrameId = requestAnimationFrame(animate);
	}

	animate();

	// iOS PWA background playback fix: use setInterval as backup
	// setInterval is less throttled than requestAnimationFrame in background
	backgroundPlaybackCheckInterval = setInterval(() => {
		if (!audio.paused && audio.duration && audio.currentTime >= audio.duration - 0.5) {
			console.log('Background check: track ended, triggering next');
			clearInterval(backgroundPlaybackCheckInterval);
			backgroundPlaybackCheckInterval = null;

			if (tracks[currentTrackIndex].looping) {
				audio.currentTime = 0;
				audio.play();
			} else {
				nextTrack();
			}
		}

		// Update Media Session position state for iOS
		if ('mediaSession' in navigator && 'setPositionState' in navigator.mediaSession) {
			try {
				if (audio.duration && !isNaN(audio.duration) && isFinite(audio.duration)) {
					navigator.mediaSession.setPositionState({
						duration: audio.duration,
						playbackRate: audio.playbackRate,
						position: audio.currentTime
					});
				}
			} catch (e) {
				// Ignore errors from setPositionState
			}
		}
	}, 100); // Check every 100ms
}

function stopProgressBar() {
	if (animationFrameId !== null) {
		cancelAnimationFrame(animationFrameId);
		animationFrameId = null;
	}
	if (backgroundPlaybackCheckInterval !== null) {
		clearInterval(backgroundPlaybackCheckInterval);
		backgroundPlaybackCheckInterval = null;
	}
}

function resetProgressBar() {
	progressBar.style.setProperty('--progress', '0');
}

function updateProgressBar() {
	if (audio.duration && !isDragging && !isSeeking) {
		const currentTime = audio.currentTime;
		const duration = audio.duration;
		const progressPercentage = (currentTime / duration) * 100;
		const displayPercentage = isNaN(progressPercentage) ? 0 : progressPercentage;
		progressBar.style.setProperty('--progress', displayPercentage);
	}
}

let isDragging = false;
let wasPlayingBeforeDrag = false;
let pendingSeekPercentage = null;
let backgroundPlaybackCheckInterval = null;

function updateVisualProgress(event) {
	if (!playerReady) return;

	const rect = progressBar.getBoundingClientRect();
	// Support both mouse and touch events
	const clientX = event.touches ? event.touches[0].clientX : event.clientX;
	const clickPosition = clientX - rect.left;
	const clickPercentage = Math.max(0, Math.min(1, clickPosition / rect.width));

	progressBar.style.setProperty('--progress', clickPercentage * 100);
	return clickPercentage;
}

let isSeeking = false;
let targetSeekTime = null;

function applySeek(clickPercentage) {
	if (!playerReady) return;

	// If audio hasn't been loaded yet, load it but don't play
	if (!audio.src || audio.src === '') {
		const track = tracks[currentTrackIndex];

		// Use preloaded blob if available, otherwise load from server
		if (preloadedAudio[track.filename]) {
			audio.src = preloadedAudio[track.filename].blobUrl;
		} else {
			audio.src = `mix/${track.filename}`;
		}

		// Wait for metadata to be loaded before seeking
		audio.addEventListener('loadedmetadata', function setInitialTime() {
			const duration = audio.duration;
			const seekTime = duration * clickPercentage;
			attemptSeekWithRetry(seekTime, clickPercentage);
			prePlaySeekTime = seekTime;
			audio.removeEventListener('loadedmetadata', setInitialTime);
		}, { once: true });
	} else if (audio.duration) {
		const duration = audio.duration;
		const seekTime = duration * clickPercentage;
		attemptSeekWithRetry(seekTime, clickPercentage);
		prePlaySeekTime = seekTime;
	}
}

function isTimeBuffered(time) {
	// Check if the given time is within any buffered time range
	for (let i = 0; i < audio.buffered.length; i++) {
		if (time >= audio.buffered.start(i) && time <= audio.buffered.end(i)) {
			return true;
		}
	}
	return false;
}

function attemptSeekWithRetry(seekTime, targetPercentage) {
	targetSeekTime = seekTime;
	isSeeking = true;

	// Lock the progress bar at the target position
	progressBar.style.setProperty('--progress', targetPercentage * 100);

	const wasPlaying = !audio.paused;

	// Try to seek
	audio.currentTime = seekTime;

	// Handler to check if we reached the target after seeking completes
	function checkSeekSuccess() {
		// Allow small tolerance for floating point comparison
		if (Math.abs(audio.currentTime - targetSeekTime) > 0.5) {
			// Browser clamped to buffered range - need to wait for more data
			// Now pause during seeking
			if (wasPlaying) {
				audio.pause();
			}
			continueSeekingToTarget(wasPlaying);
		} else {
			// Successfully reached target immediately (was already buffered)
			isSeeking = false;
			targetSeekTime = null;
			// No need to update display - the seek was instant and playback continues normally
		}
	}

	audio.addEventListener('seeked', checkSeekSuccess, { once: true });
}

function continueSeekingToTarget(wasPlaying) {
	// Handler for when more data loads
	function retrySeek() {
		if (!isSeeking || targetSeekTime === null) {
			return; // Seeking was cancelled
		}

		audio.currentTime = targetSeekTime;

		// Check again after this seek completes
		function checkAgain() {
			if (!isSeeking || targetSeekTime === null) {
				return;
			}

			if (Math.abs(audio.currentTime - targetSeekTime) > 0.5) {
				// Still not there, keep trying
				continueSeekingToTarget(wasPlaying);
			} else {
				// Success!
				isSeeking = false;
				targetSeekTime = null;

				if (wasPlaying) {
					audio.play();
				}
			}
		}

		audio.addEventListener('seeked', checkAgain, { once: true });
	}

	// Wait for more data to load, then try again
	audio.addEventListener('progress', retrySeek, { once: true });

	// Also set a timeout fallback in case progress doesn't fire
	setTimeout(() => {
		if (isSeeking && targetSeekTime !== null && Math.abs(audio.currentTime - targetSeekTime) > 0.5) {
			retrySeek();
		}
	}, 1000);
}

function onProgressMouseDown(event) {
	if (!playerReady) return;
	isDragging = true;
	wasPlayingBeforeDrag = isPlaying;
	progressContainer.style.cursor = 'grabbing';
	document.body.style.cursor = 'grabbing';
	pendingSeekPercentage = updateVisualProgress(event);
	event.preventDefault();
}

function onProgressMouseMove(event) {
	if (isDragging) {
		pendingSeekPercentage = updateVisualProgress(event);
	}
}

function onProgressMouseUp(event) {
	if (isDragging) {
		isDragging = false;
		progressContainer.style.cursor = '';
		document.body.style.cursor = '';

		// Apply the seek now that drag is complete
		if (pendingSeekPercentage !== null) {
			applySeek(pendingSeekPercentage);
			pendingSeekPercentage = null;
		}

		// If it was "Ready to play" (not playing before), start playing now
		if (!wasPlayingBeforeDrag && !isPlaying && audio.src) {
			audio.play();
			isPlaying = true;
			updatePlayPauseButton();
		}
	}
}

playPauseBtn.addEventListener('click', togglePlayPause);
nextBtn.addEventListener('click', nextTrack);
prevBtn.addEventListener('click', prevTrack);

// Mouse events for desktop
progressContainer.addEventListener('mousedown', onProgressMouseDown);
document.addEventListener('mousemove', onProgressMouseMove);
document.addEventListener('mouseup', onProgressMouseUp);

// Touch events for mobile
progressContainer.addEventListener('touchstart', onProgressMouseDown, { passive: false });
document.addEventListener('touchmove', onProgressMouseMove, { passive: false });
document.addEventListener('touchend', onProgressMouseUp);

// Keyboard controls
document.addEventListener('keydown', function(event) {
	if (!playerReady) return;

	// Spacebar: play/pause
	if (event.code === 'Space') {
		event.preventDefault();
		togglePlayPause();
	}
});

// Verify all static files are in the cache, fetching any that are missing
async function verifyStaticCache() {
	if (staticFiles.length === 0) {
		console.warn('No static files list available');
		return;
	}

	console.log(`Verifying ${staticFiles.length} static files are cached...`);

	try {
		const cache = await caches.open(CACHE_NAME);
		const cachedRequests = await cache.keys();
		const cachedUrls = new Set(cachedRequests.map(r => r.url));

		const missing = [];
		for (const file of staticFiles) {
			const absoluteUrl = file === './'
				? new URL('./', window.location.href).href
				: new URL(file, window.location.href).href;
			if (!cachedUrls.has(absoluteUrl)) {
				missing.push({ file, absoluteUrl });
			}
		}

		if (missing.length === 0) {
			console.log('All static files already cached');
			return;
		}

		console.log(`${missing.length} static files missing from cache, fetching...`);

		await Promise.all(missing.map(async ({ file, absoluteUrl }) => {
			try {
				const response = await fetchWithRetry(file);
				await cache.put(absoluteUrl, response);
				console.log(`✓ Cached missing static file: ${file}`);
			} catch (error) {
				console.error(`✗ Failed to cache static file: ${file}`, error);
			}
		}));

		console.log('Static cache verification complete');
	} catch (error) {
		console.error('Failed to verify static cache:', error);
	}

	// Preload image/SVG assets into the browser's in-memory cache
	const imageFiles = staticFiles.filter(f =>
		f.endsWith('.svg') || f.endsWith('.jpg') || f.endsWith('.png')
	);
	await Promise.all(imageFiles.map(src => new Promise(resolve => {
		const img = new Image();
		img.onload = () => {
			console.log(`Preloaded: ${src}`);
			resolve();
		};
		img.onerror = () => {
			console.error(`Failed to preload: ${src}`);
			resolve();
		};
		img.src = src;
	})));
}

function startPreloadingTracks() {
	// Start with the first track
	currentPreloadIndex = 0;
	preloadNextTrack();
}

function preloadNextTrack() {
	if (currentPreloadIndex >= tracks.length) {
		const totalMB = (totalBytesLoaded / 1024 / 1024).toFixed(2);
		console.log(`All tracks preloaded - Total size: ${totalMB} MB (${totalBytesLoaded} bytes)`);
		return;
	}

	const track = tracks[currentPreloadIndex];
	const filename = track.filename;

	// Skip if already preloaded in memory
	if (preloadedAudio[filename]) {
		currentPreloadIndex++;
		preloadNextTrack();
		return;
	}

	// If already cached, load from cache into memory
	if (cachedTracks.has(filename)) {
		console.log(`Loading from cache: ${track.artist} – ${track.title}`);
		loadFromCache(filename).then(() => {
			currentPreloadIndex++;
			setTimeout(() => preloadNextTrack(), 100);
		}).catch(err => {
			console.error(`Failed to load from cache, fetching instead:`, err);
			// If cache load fails, fetch from network
			fetchAndPreloadTrack(track, filename);
		});
		return;
	}

	console.log(`Preloading: ${track.artist} – ${track.title}`);
	fetchAndPreloadTrack(track, filename);
}

function fetchAndPreloadTrack(track, filename) {
	fetchWithRetry(`mix/${filename}`)
		.then(response => {
			const contentLength = response.headers.get('content-length');
			console.log(`Downloading ${track.title} (${(contentLength / 1024 / 1024).toFixed(2)} MB)...`);
			return response.blob();
		})
		.then(blob => {
			// Add blob size to total
			totalBytesLoaded += blob.size;

			// Create a blob URL that will persist in memory
			const blobUrl = URL.createObjectURL(blob);

			preloadedAudio[filename] = {
				blobUrl: blobUrl,
				blob: blob
			};

			console.log(`✓ Fully preloaded: ${track.artist} – ${track.title}`);

			// Store in Cache API for offline access
			return storeBlobInCache(filename, blob).then(() => {
				// Mark as cached and update UI
				cachedTracks.add(filename);
				updateTrackCachedStatus(filename);

				// Move to next track
				currentPreloadIndex++;
				setTimeout(() => preloadNextTrack(), 100);
			});
		})
		.catch(error => {
			console.error(`Failed to preload ${filename}:`, error);
			currentPreloadIndex++;
			preloadNextTrack();
		});
}

// Check which tracks are already cached on app load
async function checkCachedTracks() {
	try {
		const cache = await caches.open(CACHE_NAME);
		const cachedRequests = await cache.keys();

		// Check each track to see if it's cached
		for (const track of tracks) {
			// Build the same absolute URL that storeBlobInCache uses for consistency
			const absoluteUrl = new URL(`mix/${track.filename}`, window.location.href).href;
			const isInCache = cachedRequests.some(request => request.url === absoluteUrl);
			if (isInCache) {
				cachedTracks.add(track.filename);
			}
		}

		console.log(`Found ${cachedTracks.size}/${tracks.length} tracks already cached`);
		console.log('Cached tracks:', Array.from(cachedTracks));
	} catch (error) {
		console.error('Failed to check cached tracks:', error);
	}
}

// Debug function to check preloaded state
window.debugAudioState = function() {
	console.log('=== Audio State Debug ===');
	console.log('Player ready:', playerReady);
	console.log('Is playing:', isPlaying);
	console.log('Current track index:', currentTrackIndex);
	console.log('Total tracks:', tracks.length);
	console.log('Cached tracks count:', cachedTracks.size);
	console.log('Preloaded audio count:', Object.keys(preloadedAudio).length);
	console.log('Current audio src:', audio.src);
	console.log('Audio paused:', audio.paused);
	console.log('Audio error:', audio.error);
	if (tracks[currentTrackIndex]) {
		console.log('Current track:', tracks[currentTrackIndex].filename);
		console.log('Is preloaded:', !!preloadedAudio[tracks[currentTrackIndex].filename]);
		console.log('Is cached:', cachedTracks.has(tracks[currentTrackIndex].filename));
	}
	console.log('======================');
};

// Load a track from cache into memory
async function loadFromCache(filename) {
	try {
		const cache = await caches.open(CACHE_NAME);
		// Try both relative and absolute URLs
		let response = await cache.match(`mix/${filename}`);
		if (!response) {
			// Try with absolute URL
			const absoluteUrl = new URL(`mix/${filename}`, window.location.href).href;
			response = await cache.match(absoluteUrl);
		}

		if (!response) {
			throw new Error('Not in cache');
		}

		const blob = await response.blob();

		// Add blob size to total
		totalBytesLoaded += blob.size;

		// Create a blob URL that will persist in memory
		const blobUrl = URL.createObjectURL(blob);

		preloadedAudio[filename] = {
			blobUrl: blobUrl,
			blob: blob
		};
		console.log(`✓ Loaded from cache: ${filename}`);
	} catch (error) {
		console.error(`Failed to load from cache: ${filename}`, error);
		throw error;
	}
}

// MIME type mapping for supported audio formats
const AUDIO_MIME_TYPES = {
	'.mp3': 'audio/mpeg',
	'.m4a': 'audio/mp4',
	'.ogg': 'audio/ogg',
	'.flac': 'audio/flac',
	'.wav': 'audio/wav'
};

// Get MIME type based on file extension
function getAudioMimeType(filename) {
	const ext = filename.substring(filename.lastIndexOf('.')).toLowerCase();
	return AUDIO_MIME_TYPES[ext] || 'audio/mpeg';
}

// Store blob in Cache API for offline access
async function storeBlobInCache(filename, blob) {
	try {
		const cache = await caches.open(CACHE_NAME);
		const mimeType = getAudioMimeType(filename);
		const response = new Response(blob, {
			headers: {
				'Content-Type': mimeType,
				'Content-Length': blob.size
			}
		});
		// Use absolute URL for consistency
		const absoluteUrl = new URL(`mix/${filename}`, window.location.href).href;
		await cache.put(absoluteUrl, response);
		console.log(`✓ Cached for offline: ${filename}`);
	} catch (error) {
		console.error(`Failed to cache ${filename}:`, error);
	}
}

// Update UI to show track is cached
function updateTrackCachedStatus(filename) {
	const trackIndex = tracks.findIndex(s => s.filename === filename);
	if (trackIndex === -1) return;

	// Find the playlist item and remove uncached class
	const playlistItems = playlist.querySelectorAll('.playlist-item');
	if (playlistItems[trackIndex]) {
		const contentDiv = playlistItems[trackIndex].querySelector('.playlist-item-content');
		if (contentDiv) {
			contentDiv.classList.remove('uncached');
		}
	}
}

// Priority preloading system
function requestPriorityPreload(filename) {
	// Skip if already preloaded or already in priority queue
	if (preloadedAudio[filename] || priorityPreloadQueue.includes(filename)) {
		return;
	}

	console.log(`🔥 Priority preload requested: ${filename}`);
	priorityPreloadQueue.push(filename);

	// Start priority preloading if not already running
	if (!isPreloadingPriority) {
		processPriorityPreload();
	}
}

function processPriorityPreload() {
	if (priorityPreloadQueue.length === 0) {
		isPreloadingPriority = false;
		return;
	}

	isPreloadingPriority = true;
	const filename = priorityPreloadQueue.shift();

	// Check if already preloaded (might have finished during normal preloading)
	if (preloadedAudio[filename]) {
		processPriorityPreload();
		return;
	}

	// Find the track info
	const track = tracks.find(s => s.filename === filename);
	if (!track) {
		processPriorityPreload();
		return;
	}

	// If already cached, load from cache
	if (cachedTracks.has(filename)) {
		console.log(`🔥 Priority loading from cache: ${track.artist} – ${track.title}`);
		loadFromCache(filename).then(() => {
			processPriorityPreload();
		}).catch(err => {
			console.error(`Failed to load from cache, fetching instead:`, err);
			priorityFetchAndPreloadTrack(track, filename);
		});
		return;
	}

	console.log(`🔥 Priority preloading: ${track.artist} – ${track.title}`);
	priorityFetchAndPreloadTrack(track, filename);
}

function priorityFetchAndPreloadTrack(track, filename) {
	fetchWithRetry(`mix/${filename}`)
		.then(response => {
			return response.blob();
		})
		.then(blob => {
			// Create a blob URL that will persist in memory
			const blobUrl = URL.createObjectURL(blob);

			preloadedAudio[filename] = {
				blobUrl: blobUrl,
				blob: blob
			};

			// Next time this track plays, it will use the cached version
			console.log(`✓ Priority preloaded: ${track.artist} – ${track.title}`);

			// Store in Cache API for offline access
			return storeBlobInCache(filename, blob).then(() => {
				// Mark as cached and update UI
				cachedTracks.add(filename);
				updateTrackCachedStatus(filename);

				// Process next priority request
				processPriorityPreload();
			});
		})
		.catch(error => {
			// Ignore abort errors (happens when normal preload finishes first)
			if (error.name === 'AbortError' || error.message.includes('aborted')) {
				// This is expected - normal preloading probably finished first
			} else {
				console.error(`Failed to priority preload ${filename}:`, error);
			}
			processPriorityPreload();
		});
}
