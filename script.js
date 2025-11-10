// Register service worker for PWA functionality
if ('serviceWorker' in navigator) {
	window.addEventListener('load', () => {
		navigator.serviceWorker.register('service-worker.js')
			.then(registration => {
				console.log('Service Worker registered successfully:', registration.scope);
			})
			.catch(error => {
				console.log('Service Worker registration failed:', error);
			});
	});
}

const playPauseBtn = document.getElementById('playPause');
const prevBtn = document.getElementById('prev');
const nextBtn = document.getElementById('next');
const playlist = document.getElementById('playlist');
const currentSongDisplay = document.getElementById('currentSong');
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

let currentSongIndex = 0;
let isPlaying = false;
let progressInterval;
let playerReady = false;
let songs = [];
let animationFrameId = null;
let prePlaySeekTime = 0;
let preloadedAudio = {}; // Cache for preloaded audio elements
let currentPreloadIndex = 0;
let priorityPreloadQueue = []; // Songs requested by user that need priority preloading
let isPreloadingPriority = false;
let totalBytesLoaded = 0; // Track total filesize of all preloaded songs
let cachedTracks = new Set(); // Track which songs are cached for offline use
let CACHE_NAME = null; // Will be loaded from manifest.json

// Load cache name from manifest.json first, then load tracks
fetch('manifest.json')
	.then(response => response.json())
	.then(manifest => {
		CACHE_NAME = manifest.cache_name || manifest.name;
		console.log('Using cache name:', CACHE_NAME);

		// Now that we have CACHE_NAME, load tracks
		return fetch('tracks.json');
	})
	.then(response => {
		if (!response.ok) {
			throw new Error('tracks.json not found');
		}
		return response.json();
	})
	.then(data => {
		songs = shuffle ? shuffleArray(data) : data;
		if (songs.length > 0) {
			playerReady = true;
			updateCurrentSongDisplay(`Ready to play: ${songs[0].artist} – ${songs[0].title}`);
			// Check which tracks are already cached before rendering
			return checkCachedTracks().then(() => {
				renderPlaylist();
				// Pre-cache resources first, then songs
				return preloadResources().then(() => {
					startPreloadingSongs();
				});
			});
		} else {
			updateCurrentSongDisplay('No tracks found');
		}
	})
	.catch(error => {
		console.error('Error loading manifest or tracks:', error);
		updateCurrentSongDisplay('Unable to load tracks. Please check your connection.');
	});

// Audio event listeners
audio.addEventListener('play', () => {
	startProgressBar();
	const song = songs[currentSongIndex];
	const songText = `${song.artist} – ${song.title}`;

	// Always update display to ensure we remove "Ready to play:" prefix
	const currentText = currentSongDisplay.querySelector('span')?.textContent || '';

	// Check if it's a different song (not just play/pause of same song)
	const isNewSong = !currentText.includes(songText);
	const hasReadyToPlay = currentText.includes('Ready to play:');

	if (isNewSong || hasReadyToPlay) {
		updateCurrentSongDisplay(songText);
	} else {
		// Same song, just resume the marquee
		resumeMarquee();
	}

	// Update media session metadata
	if ('mediaSession' in navigator) {
		// Convert relative path to absolute URL for media session
		// Use document.baseURI to correctly resolve paths in subdirectories
		const albumArtUrl = new URL('resources/album_art.jpg', document.baseURI).href;
		navigator.mediaSession.metadata = new MediaMetadata({
			title: song.title,
			artist: song.artist,
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
				prevSong();
			}
		});

		navigator.mediaSession.setActionHandler('nexttrack', () => {
			if (playerReady) {
				nextSong();
			}
		});

		// Explicitly set seek handlers to null to show track controls instead
		navigator.mediaSession.setActionHandler('seekbackward', null);
		navigator.mediaSession.setActionHandler('seekforward', null);
	}
});

audio.addEventListener('pause', () => {
	stopProgressBar();
	pauseMarquee();
});

audio.addEventListener('ended', () => {
	if (songs[currentSongIndex].looping) {
		audio.currentTime = 0;
		audio.play();
	} else {
		nextSong();
	}
});

audio.addEventListener('error', (e) => {
	console.error('Audio error:', e);
	updateCurrentSongDisplay(`Error loading: ${songs[currentSongIndex].filename}`);
	// Try next song after a brief delay
	setTimeout(() => nextSong(), 1000);
});

audio.addEventListener('loadedmetadata', () => {
	resetProgressBar();
});

function renderPlaylist() {
	playlist.innerHTML = '';
	const currentDisplayText = currentSongDisplay.textContent;
	const isInitialized = currentDisplayText !== 'No song playing';

	songs.forEach((song, index) => {
		const item = document.createElement('div');
		item.classList.add('playlist-item');

		const contentDiv = document.createElement('div');
		contentDiv.classList.add('playlist-item-content');

		const titleDiv = document.createElement('div');
		titleDiv.classList.add('playlist-item-title');
		if (isInitialized && index === currentSongIndex) {
			titleDiv.classList.add('current');
		}
		titleDiv.textContent = song.title;

		const artistDiv = document.createElement('div');
		artistDiv.classList.add('playlist-item-artist');
		if (isInitialized && index === currentSongIndex) {
			artistDiv.classList.add('current');
		}
		artistDiv.textContent = song.artist;

		// Set cached status for visual indication
		const isCached = cachedTracks.has(song.filename);
		if (!isCached) {
			contentDiv.classList.add('uncached');
		}

		contentDiv.appendChild(titleDiv);
		contentDiv.appendChild(artistDiv);

		const loopIcon = document.createElement('span');
		loopIcon.textContent = '🔁';
		loopIcon.style.display = (song.looping || false) ? 'inline' : 'none';

		item.appendChild(contentDiv);
		item.appendChild(loopIcon);
		item.addEventListener('click', () => toggleLooping(index));
		playlist.appendChild(item);
	});
}

function toggleLooping(index) {
	if (!playerReady) return;
	if (index === currentSongIndex) {
		if (!isPlaying && currentSongDisplay.textContent.includes('Ready to play')) {
			audio.play().catch(err => {
				console.error('Failed to play audio:', err);
			});
			isPlaying = true;
			updatePlayPauseButton();
			return;
		}
		// Toggle looping
		songs[index].looping = !(songs[index].looping || false);
		renderPlaylist();
	} else {
		playSong(index);
	}
}

function playSong(index) {
	console.log(`playSong called with index: ${index}`);
	if (!playerReady) {
		console.log('Player not ready');
		return;
	}
	// Clear looping from all songs except the new one if it was already looping
	const wasLooping = songs[index].looping || false;
	songs.forEach(song => song.looping = false);
	if (wasLooping) {
		songs[index].looping = true;
	}

	currentSongIndex = index;
	const song = songs[currentSongIndex];
	console.log(`Attempting to play: ${song.artist} – ${song.title}`);
	console.log(`Filename: ${song.filename}`);
	console.log(`Is in preloadedAudio: ${!!preloadedAudio[song.filename]}`);

	// Use preloaded blob if available, otherwise load from server
	if (preloadedAudio[song.filename]) {
		const blobUrl = preloadedAudio[song.filename].blobUrl;
		console.log(`Playing from preloaded blob: ${song.filename}`);
		console.log(`Blob URL: ${blobUrl}`);
		audio.src = blobUrl;
	} else {
		console.log(`Song not preloaded, loading: ${song.filename}`);
		audio.src = `tracks/${song.filename}`;
		// Request priority preloading for this song
		requestPriorityPreload(song.filename);
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
			updateCurrentSongDisplay(`Error playing: ${song.title}`);
		});
	}

	// Optimistically set playing state
	isPlaying = true;
	updatePlayPauseButton();
	renderPlaylist();
}

function updateCurrentSongDisplay(text) {
	currentSongDisplay.innerHTML = `<span>${text}</span>`;
	// Initialize marquee effect after a brief delay to ensure DOM is updated
	setTimeout(() => setupMarquee(), 50);
}

// Marquee state
let marqueeAnimating = false;
let marqueePaused = false;
let marqueeTimeoutId = null;
let marqueeOriginalText = '';
let marqueeDuration = 0;
let marqueeHalfWidth = 0;
let marqueeTransitionEndHandler = null;
let marqueeCurrentTransform = 'translateX(0)';

function setupMarquee() {
	const container = currentSongDisplay;
	const textSpan = container.querySelector('span');

	if (!textSpan) return;

	// Clear any existing animation
	if (marqueeTimeoutId) {
		clearTimeout(marqueeTimeoutId);
		marqueeTimeoutId = null;
	}
	if (marqueeTransitionEndHandler) {
		textSpan.removeEventListener('transitionend', marqueeTransitionEndHandler);
		marqueeTransitionEndHandler = null;
	}
	marqueeAnimating = false;
	marqueePaused = false;

	// Reset styles
	textSpan.style.transition = 'none';
	textSpan.style.transform = 'translateX(0)';
	marqueeCurrentTransform = 'translateX(0)';
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
	marqueeDuration = (marqueeHalfWidth / 50) * 1000; // Adjust speed here (pixels per second)

	// Start animation after a brief delay (only if not paused)
	// Don't start animation if already paused
	if (!marqueePaused) {
		marqueeTimeoutId = setTimeout(() => {
			if (marqueePaused) return;

			textSpan.style.transition = `transform ${marqueeDuration}ms linear`;
			textSpan.style.transform = `translateX(-${marqueeHalfWidth}px)`;
			marqueeCurrentTransform = `translateX(-${marqueeHalfWidth}px)`;

			// Reset and loop
			marqueeTransitionEndHandler = () => {
				if (!marqueeAnimating || marqueePaused) return;

				textSpan.style.transition = 'none';
				textSpan.style.transform = 'translateX(0)';
				marqueeCurrentTransform = 'translateX(0)';

				setTimeout(() => {
					if (!marqueeAnimating || marqueePaused) return;
					textSpan.style.transition = `transform ${marqueeDuration}ms linear`;
					textSpan.style.transform = `translateX(-${marqueeHalfWidth}px)`;
					marqueeCurrentTransform = `translateX(-${marqueeHalfWidth}px)`;
				}, 50);
			};

			textSpan.addEventListener('transitionend', marqueeTransitionEndHandler);
		}, 1000); // Initial delay before starting scroll
	}
}

function pauseMarquee() {
	marqueePaused = true;
	const textSpan = currentSongDisplay.querySelector('span');
	if (!textSpan || !marqueeAnimating) return;

	// Capture current transform position
	const computedStyle = window.getComputedStyle(textSpan);
	const currentTransform = computedStyle.transform;
	marqueeCurrentTransform = currentTransform;

	// Freeze at current position
	textSpan.style.transition = 'none';
	textSpan.style.transform = currentTransform;

	// Clear any pending timeout
	if (marqueeTimeoutId) {
		clearTimeout(marqueeTimeoutId);
		marqueeTimeoutId = null;
	}
}

function resumeMarquee() {
	if (!marqueeAnimating) return;
	marqueePaused = false;

	const textSpan = currentSongDisplay.querySelector('span');
	if (!textSpan) return;

	// Apply the stored transform position first
	textSpan.style.transition = 'none';
	textSpan.style.transform = marqueeCurrentTransform;

	// Force reflow to apply the transform
	void textSpan.offsetWidth;

	// Get current position from the stored transform
	const matrix = new DOMMatrix(marqueeCurrentTransform);
	const currentX = matrix.m41;

	// Calculate remaining distance and time
	const distanceTraveled = Math.abs(currentX);
	const percentComplete = distanceTraveled / marqueeHalfWidth;
	const timeRemaining = marqueeDuration * (1 - percentComplete);

	// Resume animation from current position
	textSpan.style.transition = `transform ${timeRemaining}ms linear`;
	textSpan.style.transform = `translateX(-${marqueeHalfWidth}px)`;
	marqueeCurrentTransform = `translateX(-${marqueeHalfWidth}px)`;
}

// Add window resize listener to recalculate marquee
window.addEventListener('resize', () => {
	if (marqueeOriginalText) {
		// Store the paused state before recalculating
		const wasPaused = marqueePaused;

		// Restore original text before recalculating
		const textSpan = currentSongDisplay.querySelector('span');
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
		// If no song is loaded, load the first one
		if (!audio.src || audio.src === '') {
			playSong(currentSongIndex);
		} else {
			audio.play().catch(err => {
				console.error('Failed to play audio:', err);
				const song = songs[currentSongIndex];
				updateCurrentSongDisplay(`Error playing: ${song.title}`);
			});
			isPlaying = true;
		}
	}
	updatePlayPauseButton();
}

function updatePlayPauseButton() {
	playPauseBtn.classList.toggle('pause', isPlaying);
}

function nextSong() {
	if (!playerReady) return;
	currentSongIndex = (currentSongIndex + 1) % songs.length;
	playSong(currentSongIndex);
}

function prevSong() {
	if (!playerReady) return;
	if (audio.currentTime <= 3) {
		currentSongIndex = (currentSongIndex - 1 + songs.length) % songs.length;
		playSong(currentSongIndex);
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
			console.log('Background check: song ended, triggering next');
			clearInterval(backgroundPlaybackCheckInterval);
			backgroundPlaybackCheckInterval = null;

			if (songs[currentSongIndex].looping) {
				audio.currentTime = 0;
				audio.play();
			} else {
				nextSong();
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
	}, 500); // Check every 500ms
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
		const song = songs[currentSongIndex];

		// Use preloaded blob if available, otherwise load from server
		if (preloadedAudio[song.filename]) {
			audio.src = preloadedAudio[song.filename].blobUrl;
		} else {
			audio.src = `tracks/${song.filename}`;
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
nextBtn.addEventListener('click', nextSong);
prevBtn.addEventListener('click', prevSong);

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

// Pre-caching system
function preloadResources() {
	console.log('Preloading UI resources...');

	const resources = [
		'resources/play.png',
		'resources/pause.png',
		'resources/prev.png',
		'resources/next.png',
		'resources/album_art.jpg'
	];

	const imagePromises = resources.map(src => {
		return new Promise((resolve, reject) => {
			const img = new Image();
			img.onload = () => {
				console.log(`Preloaded: ${src}`);
				resolve();
			};
			img.onerror = () => {
				console.error(`Failed to preload: ${src}`);
				resolve(); // Resolve anyway to not block other resources
			};
			img.src = src;
		});
	});

	return Promise.all(imagePromises).then(() => {
		console.log('All UI resources preloaded');
	});
}

function startPreloadingSongs() {
	// Start with the first song
	currentPreloadIndex = 0;
	preloadNextSong();
}

function preloadNextSong() {
	if (currentPreloadIndex >= songs.length) {
		const totalMB = (totalBytesLoaded / 1024 / 1024).toFixed(2);
		console.log(`All songs preloaded - Total size: ${totalMB} MB (${totalBytesLoaded} bytes)`);
		return;
	}

	const song = songs[currentPreloadIndex];
	const filename = song.filename;

	// Skip if already preloaded in memory
	if (preloadedAudio[filename]) {
		currentPreloadIndex++;
		preloadNextSong();
		return;
	}

	// If already cached, load from cache into memory
	if (cachedTracks.has(filename)) {
		console.log(`Loading from cache: ${song.artist} – ${song.title}`);
		loadFromCache(filename).then(() => {
			currentPreloadIndex++;
			setTimeout(() => preloadNextSong(), 100);
		}).catch(err => {
			console.error(`Failed to load from cache, fetching instead:`, err);
			// If cache load fails, fetch from network
			fetchAndPreloadSong(song, filename);
		});
		return;
	}

	console.log(`Preloading: ${song.artist} – ${song.title}`);
	fetchAndPreloadSong(song, filename);
}

function fetchAndPreloadSong(song, filename) {
	// Use fetch to force full download of the entire file
	fetch(`tracks/${filename}`)
		.then(response => {
			if (!response.ok) {
				throw new Error(`HTTP error! status: ${response.status}`);
			}
			// Get total file size for progress tracking
			const contentLength = response.headers.get('content-length');
			console.log(`Downloading ${song.title} (${(contentLength / 1024 / 1024).toFixed(2)} MB)...`);

			// Read the entire response as a blob
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

			console.log(`✓ Fully preloaded: ${song.artist} – ${song.title}`);

			// Store in Cache API for offline access
			return storeBlobInCache(filename, blob).then(() => {
				// Mark as cached and update UI
				cachedTracks.add(filename);
				updateTrackCachedStatus(filename);

				// Move to next song
				currentPreloadIndex++;
				setTimeout(() => preloadNextSong(), 100);
			});
		})
		.catch(error => {
			console.error(`Failed to preload ${filename}:`, error);
			currentPreloadIndex++;
			preloadNextSong();
		});
}

// Check which tracks are already cached on app load
async function checkCachedTracks() {
	try {
		const cache = await caches.open(CACHE_NAME);
		const cachedRequests = await cache.keys();

		// Check each song to see if it's cached
		for (const song of songs) {
			// Build the same absolute URL that storeBlobInCache uses for consistency
			const absoluteUrl = new URL(`tracks/${song.filename}`, window.location.href).href;
			const isInCache = cachedRequests.some(request => request.url === absoluteUrl);
			if (isInCache) {
				cachedTracks.add(song.filename);
			}
		}

		console.log(`Found ${cachedTracks.size}/${songs.length} tracks already cached`);
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
	console.log('Current song index:', currentSongIndex);
	console.log('Total songs:', songs.length);
	console.log('Cached tracks count:', cachedTracks.size);
	console.log('Preloaded audio count:', Object.keys(preloadedAudio).length);
	console.log('Current audio src:', audio.src);
	console.log('Audio paused:', audio.paused);
	console.log('Audio error:', audio.error);
	if (songs[currentSongIndex]) {
		console.log('Current song:', songs[currentSongIndex].filename);
		console.log('Is preloaded:', !!preloadedAudio[songs[currentSongIndex].filename]);
		console.log('Is cached:', cachedTracks.has(songs[currentSongIndex].filename));
	}
	console.log('======================');
};

// Load a track from cache into memory
async function loadFromCache(filename) {
	try {
		const cache = await caches.open(CACHE_NAME);
		// Try both relative and absolute URLs
		let response = await cache.match(`tracks/${filename}`);
		if (!response) {
			// Try with absolute URL
			const absoluteUrl = new URL(`tracks/${filename}`, window.location.href).href;
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

// Store blob in Cache API for offline access
async function storeBlobInCache(filename, blob) {
	try {
		const cache = await caches.open(CACHE_NAME);
		const response = new Response(blob, {
			headers: {
				'Content-Type': 'audio/mpeg',
				'Content-Length': blob.size
			}
		});
		// Use absolute URL for consistency
		const absoluteUrl = new URL(`tracks/${filename}`, window.location.href).href;
		await cache.put(absoluteUrl, response);
		console.log(`✓ Cached for offline: ${filename}`);
	} catch (error) {
		console.error(`Failed to cache ${filename}:`, error);
	}
}

// Update UI to show track is cached
function updateTrackCachedStatus(filename) {
	const songIndex = songs.findIndex(s => s.filename === filename);
	if (songIndex === -1) return;

	// Find the playlist item and remove uncached class
	const playlistItems = playlist.querySelectorAll('.playlist-item');
	if (playlistItems[songIndex]) {
		const contentDiv = playlistItems[songIndex].querySelector('.playlist-item-content');
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

	// Find the song info
	const song = songs.find(s => s.filename === filename);
	if (!song) {
		processPriorityPreload();
		return;
	}

	// If already cached, load from cache
	if (cachedTracks.has(filename)) {
		console.log(`🔥 Priority loading from cache: ${song.artist} – ${song.title}`);
		loadFromCache(filename).then(() => {
			processPriorityPreload();
		}).catch(err => {
			console.error(`Failed to load from cache, fetching instead:`, err);
			priorityFetchAndPreloadSong(song, filename);
		});
		return;
	}

	console.log(`🔥 Priority preloading: ${song.artist} – ${song.title}`);
	priorityFetchAndPreloadSong(song, filename);
}

function priorityFetchAndPreloadSong(song, filename) {
	// Use fetch to force full download of the entire file
	fetch(`tracks/${filename}`)
		.then(response => {
			if (!response.ok) {
				throw new Error(`HTTP error! status: ${response.status}`);
			}
			return response.blob();
		})
		.then(blob => {
			// Create a blob URL that will persist in memory
			const blobUrl = URL.createObjectURL(blob);

			preloadedAudio[filename] = {
				blobUrl: blobUrl,
				blob: blob
			};

			// Next time this song plays, it will use the cached version
			console.log(`✓ Priority preloaded: ${song.artist} – ${song.title}`);

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
