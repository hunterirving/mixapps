/* Local-only reorder/rename code used when refining your mix via serve.py */

// Drag to reorder

const REORDER_DRAG_THRESHOLD = 5;
const LONG_PRESS_MS = 400;
const LONG_PRESS_MOVE_TOLERANCE = 10;
let activeReorder = null;
let longPressTimer = null;

function attachReorderHandlers(item, index) {
	item.addEventListener('mousedown', (e) => {
		// Ignore non-primary buttons
		if (e.button !== 0) return;
		startReorder(item, index, e.clientX, e.clientY);
	});

	item.addEventListener('touchstart', (e) => {
		if (e.touches.length !== 1) return;
		const t = e.touches[0];
		startLongPress(item, index, t.clientX, t.clientY);
	}, { passive: true });
}

function startLongPress(item, index, startX, startY) {
	if (longPressTimer) clearTimeout(longPressTimer);

	const candidate = { item, index, startX, startY };
	longPressTimer = setTimeout(() => {
		longPressTimer = null;
		cleanup();
		startReorder(candidate.item, candidate.index, candidate.startX, candidate.startY, /* isTouch */ true);
		beginDrag();
		if (navigator.vibrate) navigator.vibrate(10);
	}, LONG_PRESS_MS);

	const onMove = (e) => {
		const t = e.touches[0];
		if (!t) return;
		const dx = t.clientX - startX;
		const dy = t.clientY - startY;
		if (Math.hypot(dx, dy) > LONG_PRESS_MOVE_TOLERANCE) cancel();
	};
	const onUp = () => cancel();

	function cleanup() {
		document.removeEventListener('touchmove', onMove);
		document.removeEventListener('touchend', onUp);
	}

	function cancel() {
		if (longPressTimer) {
			clearTimeout(longPressTimer);
			longPressTimer = null;
		}
		cleanup();
	}

	document.addEventListener('touchmove', onMove, { passive: true });
	document.addEventListener('touchend', onUp);
}

function startReorder(item, index, startX, startY, isTouch = false) {
	activeReorder = {
		item,
		index,
		startX,
		startY,
		started: false,
		placeholder: null,
		offsetY: 0,
		itemHeight: 0,
		autoScrollRaf: null,
		autoScrollSpeed: 0,
		lastClientY: startY,
		isTouch,
	};
	if (isTouch) {
		document.addEventListener('touchmove', onReorderTouchMove, { passive: false });
		document.addEventListener('touchend', onReorderEnd);
		document.addEventListener('touchcancel', onReorderEnd);
	} else {
		document.body.classList.add('reorder-pressed');
		document.addEventListener('mousemove', onReorderMove);
		document.addEventListener('mouseup', onReorderEnd);
	}
}

function beginDrag() {
	const r = activeReorder;
	const rect = r.item.getBoundingClientRect();
	const playlistRect = playlist.getBoundingClientRect();
	r.itemHeight = rect.height;
	r.offsetY = r.startY - rect.top;

	const styles = window.getComputedStyle(r.item);
	const placeholder = document.createElement('div');
	placeholder.classList.add('playlist-item-placeholder');
	placeholder.style.height = `${rect.height}px`;
	placeholder.style.marginTop = styles.marginTop;
	placeholder.style.marginBottom = styles.marginBottom;
	placeholder.style.paddingLeft = styles.paddingLeft;
	placeholder.style.paddingRight = styles.paddingRight;
	placeholder.style.paddingBottom = styles.paddingBottom;
	r.item.parentNode.insertBefore(placeholder, r.item);
	r.placeholder = placeholder;

	r.item.classList.add('dragging');
	r.item.style.position = 'fixed';
	r.item.style.left = `${playlistRect.left}px`;
	r.item.style.top = `${rect.top}px`;
	r.item.style.width = `${playlistRect.width}px`;
	r.item.style.height = `${rect.height}px`;
	r.item.style.zIndex = '10';
	document.body.appendChild(r.item);
	// Now we're actually dragging — disable pointer-events on the other items
	document.body.classList.add('reordering');

	r.started = true;
	r.item._suppressClick = true;
}

function onReorderMove(e) {
	const r = activeReorder;
	if (!r) return;
	r.lastClientY = e.clientY;

	if (!r.started) {
		const dx = e.clientX - r.startX;
		const dy = e.clientY - r.startY;
		if (Math.hypot(dx, dy) < REORDER_DRAG_THRESHOLD) return;
		beginDrag();
	}

	positionDraggedItem();
	updateAutoScroll();
}

function onReorderTouchMove(e) {
	const r = activeReorder;
	if (!r || !r.started) return;
	e.preventDefault();
	const t = e.touches[0];
	if (!t) return;
	r.lastClientY = t.clientY;
	positionDraggedItem();
	updateAutoScroll();
}

function positionDraggedItem() {
	const r = activeReorder;
	if (!r || !r.started) return;

	// Clamp the dragged item between the bottom of the now-playing area
	// (the wrapper's top) and the top of the navigation controls.
	const wrapperRect = playlistWrapper.getBoundingClientRect();
	const controlsRect = controls.getBoundingClientRect();
	const desiredTop = r.lastClientY - r.offsetY;
	const minTop = wrapperRect.top;
	const maxTop = controlsRect.top - r.itemHeight;
	const clampedTop = Math.max(minTop, Math.min(maxTop, desiredTop));
	r.item.style.top = `${clampedTop}px`;

	repositionPlaceholder();
}

function layoutMidY(el) {
	const rect = el.getBoundingClientRect();
	if (el._flipTargetTop !== undefined) {
		return el._flipTargetTop + rect.height / 2;
	}
	return rect.top + rect.height / 2;
}

function repositionPlaceholder() {
	const r = activeReorder;
	if (!r || !r.started) return;

	const draggedRect = r.item.getBoundingClientRect();
	const draggedMid = draggedRect.top + draggedRect.height / 2;

	const prev = r.placeholder.previousElementSibling;
	if (prev && prev.classList.contains('playlist-item')) {
		if (draggedMid < layoutMidY(prev)) {
			flipItem(prev, () => playlist.insertBefore(r.placeholder, prev));
			return;
		}
	}

	const next = r.placeholder.nextElementSibling;
	if (next && next.classList.contains('playlist-item')) {
		if (draggedMid > layoutMidY(next)) {
			flipItem(next, () => playlist.insertBefore(r.placeholder, next.nextSibling));
			return;
		}
	}
}

const AUTO_SCROLL_EDGE = 60; // px from edge that triggers scrolling
const AUTO_SCROLL_MAX_SPEED = 6; // px per frame

function updateAutoScroll() {
	const r = activeReorder;
	if (!r || !r.started) return;

	const wrapperRect = playlistWrapper.getBoundingClientRect();
	const bottomBound = controls.getBoundingClientRect().top;
	const y = r.lastClientY;

	let speed = 0;
	if (y < wrapperRect.top + AUTO_SCROLL_EDGE) {
		const intensity = (wrapperRect.top + AUTO_SCROLL_EDGE - y) / AUTO_SCROLL_EDGE;
		speed = -Math.min(1, intensity) * AUTO_SCROLL_MAX_SPEED;
	} else if (y > bottomBound - AUTO_SCROLL_EDGE) {
		const intensity = (y - (bottomBound - AUTO_SCROLL_EDGE)) / AUTO_SCROLL_EDGE;
		speed = Math.min(1, intensity) * AUTO_SCROLL_MAX_SPEED;
	}

	r.autoScrollSpeed = speed;
	if (speed !== 0 && !r.autoScrollRaf) {
		const tick = () => {
			const cur = activeReorder;
			if (!cur || !cur.started || cur.autoScrollSpeed === 0) {
				if (cur) cur.autoScrollRaf = null;
				return;
			}
			const before = playlistWrapper.scrollTop;
			playlistWrapper.scrollTop = Math.max(0, Math.min(playlistWrapper.scrollHeight - playlistWrapper.clientHeight, playlistWrapper.scrollTop + cur.autoScrollSpeed));
			const delta = playlistWrapper.scrollTop - before;
			if (delta !== 0) {
				positionDraggedItem();
			}
			cur.autoScrollRaf = requestAnimationFrame(tick);
		};
		r.autoScrollRaf = requestAnimationFrame(tick);
	}
}

function flipItem(el, mutate) {
	el.style.transition = 'none';
	el.style.transform = '';
	const oldTop = el.getBoundingClientRect().top;

	mutate();

	const newTop = el.getBoundingClientRect().top;
	const dy = oldTop - newTop;
	if (!dy) return;
	el.style.transform = `translateY(${dy}px)`;
	void el.offsetHeight;
	el.style.transition = 'transform 180ms ease';
	el.style.transform = '';

	el._flipTargetTop = newTop;
	if (el._flipEndHandler) el.removeEventListener('transitionend', el._flipEndHandler);
	el._flipEndHandler = (e) => {
		if (e.propertyName !== 'transform') return;
		delete el._flipTargetTop;
		el.removeEventListener('transitionend', el._flipEndHandler);
		el._flipEndHandler = null;
	};
	el.addEventListener('transitionend', el._flipEndHandler);
}

function onReorderEnd() {
	const r = activeReorder;
	document.removeEventListener('mousemove', onReorderMove);
	document.removeEventListener('mouseup', onReorderEnd);
	document.removeEventListener('touchmove', onReorderTouchMove);
	document.removeEventListener('touchend', onReorderEnd);
	document.removeEventListener('touchcancel', onReorderEnd);
	activeReorder = null;
	document.body.classList.remove('reorder-pressed');
	document.body.classList.remove('reordering');
	if (r && r.autoScrollRaf) cancelAnimationFrame(r.autoScrollRaf);
	if (!r) return;

	if (!r.started) {
		// No real drag — let the click handler fire normally
		return;
	}

	// Compute the new order from placeholder position and rebuild tracks array
	const fromIndex = r.index;
	const itemsInDom = Array.from(playlist.querySelectorAll('.playlist-item, .playlist-item-placeholder'));
	const toIndex = itemsInDom.indexOf(r.placeholder);

	const droppedTop = r.item.getBoundingClientRect().top;
	r.placeholder.remove();

	if (toIndex === -1 || toIndex === fromIndex) {
		renderPlaylist();
		animateDroppedTrack(r.item, fromIndex, droppedTop);
		return;
	}

	// Build the new tracks array directly from the DOM ordering.
	const moved = tracks[fromIndex];
	const remaining = tracks.filter((_, i) => i !== fromIndex);
	const newTracks = [];
	let remainingIdx = 0;
	for (let i = 0; i < itemsInDom.length; i++) {
		if (itemsInDom[i] === r.placeholder) {
			newTracks.push(moved);
		} else {
			newTracks.push(remaining[remainingIdx++]);
		}
	}

	const playingTrack = tracks[currentTrackIndex];
	tracks.length = 0;
	tracks.push(...newTracks);
	const newCurrentIndex = tracks.indexOf(playingTrack);
	if (newCurrentIndex !== -1) setCurrentTrackIndex(newCurrentIndex);

	renderPlaylist();
	animateDroppedTrack(r.item, toIndex, droppedTop);
	saveTrackOrder();
}

function animateDroppedTrack(draggedEl, newIndex, oldTop) {
	const items = playlist.querySelectorAll('.playlist-item');
	const target = items[newIndex];
	if (!target) {
		draggedEl.remove();
		return;
	}

	// Hide the rebuilt item but keep it in layout so sizing/scroll are stable.
	target.style.visibility = 'hidden';
	const newTop = target.getBoundingClientRect().top;

	const cleanup = () => {
		draggedEl.remove();
		target.style.visibility = '';
	};

	if (oldTop === newTop) {
		cleanup();
		return;
	}

	const playlistRect = playlist.getBoundingClientRect();
	draggedEl.style.transition = 'none';
	draggedEl.style.top = `${oldTop}px`;
	draggedEl.style.left = `${playlistRect.left}px`;
	draggedEl.style.width = `${playlistRect.width}px`;
	void draggedEl.offsetHeight;
	draggedEl.style.transition = 'top 180ms ease';
	draggedEl.style.top = `${newTop}px`;

	const finish = (e) => {
		if (e.propertyName !== 'top') return;
		draggedEl.removeEventListener('transitionend', finish);
		cleanup();
	};
	draggedEl.addEventListener('transitionend', finish);
}

function saveTrackOrder() {
	// Strip the runtime-only `looping` flag so we don't persist transient UI state
	const persisted = tracks.map(({ looping, ...rest }) => rest);
	fetch('/tracks', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(persisted),
	}).catch(err => console.error('Failed to save order:', err));
}

// Live sync over SSE

// Swap the now-playing text without disturbing an in-flight marquee
function updateNowPlayingTextInPlace(text) {
	const span = currentTrackDisplay.querySelector('span');
	if (!span) {
		updateCurrentTrackDisplay(text);
		return;
	}

	// If the marquee isn't currently animating, decide whether the new text needs animation
	if (!marqueeAnimating) {
		span.textContent = text;
		const containerWidth = currentTrackDisplay.offsetWidth - 30;
		if (span.scrollWidth > containerWidth) {
			marqueeOriginalText = text;
			setupMarquee({ preserveOffset: true });
		} else {
			marqueeOriginalText = text;
		}
		return;
	}

	// Marquee is animating. Update the duplicated text in place, recompute
	// the half-width (since the new text may differ in length), and wrap
	// the current offset into the new range
	marqueeOriginalText = text;
	const spacing = '            ';
	span.textContent = text + spacing + text + spacing;

	const containerWidth = currentTrackDisplay.offsetWidth - 30;
	if (span.scrollWidth / 2 <= containerWidth) {
		// New text fits — stop the marquee cleanly.
		setupMarquee({ preserveOffset: true });
		return;
	}

	marqueeHalfWidth = span.scrollWidth / 2;
	marqueeOffset = marqueeOffset % marqueeHalfWidth;
	span.style.transform = `translateX(-${marqueeOffset}px)`;
}

// Skip the very first SSE message so we don't double-render before the player has finished its
// initial setup.
let sseSeenInitial = false;

function tracksEqual(a, b) {
	if (a.length !== b.length) return false;
	for (let i = 0; i < a.length; i++) {
		if (a[i].filename !== b[i].filename) return false;
		if (a[i].title !== b[i].title) return false;
		if (a[i].artist !== b[i].artist) return false;
	}
	return true;
}

function applyRenames(renames) {
	for (const { from, to } of renames) {
		if (from === to) continue;

		if (preloadedAudio[from]) {
			preloadedAudio[to] = preloadedAudio[from];
			delete preloadedAudio[from];
		}

		if (cachedTracks.has(from)) {
			cachedTracks.delete(from);
			cachedTracks.add(to);
		}

		const oldUrl = `mix/${from}`;
		if (audio.src && audio.src.endsWith(oldUrl)) {
			const wasPlaying = !audio.paused;
			const t = audio.currentTime;
			audio.src = `mix/${to}`;
			audio.load();
			audio.addEventListener('loadedmetadata', function resume() {
				audio.removeEventListener('loadedmetadata', resume);
				try { audio.currentTime = t; } catch (e) {}
				if (wasPlaying) audio.play().catch(() => {});
			}, { once: true });
		}

		const idx = tracks.findIndex(t => t.filename === from);
		if (idx !== -1) tracks[idx].filename = to;
	}
}

function reconcileTracks(incoming, renames) {
	if (renames && renames.length) applyRenames(renames);

	const incomingByName = new Map(incoming.map(t => [t.filename, t]));
	const currentNames = new Set(tracks.map(t => t.filename));
	const incomingNames = new Set(incomingByName.keys());

	if (tracks.length > 0 && tracksEqual(tracks, incoming)) return;

	const playingFilename = tracks[currentTrackIndex] && tracks[currentTrackIndex].filename;
	const playingRemoved = playingFilename && !incomingNames.has(playingFilename);

	// Free blob URLs for tracks that disappeared.
	for (const name of currentNames) {
		if (!incomingNames.has(name) && preloadedAudio[name]) {
			try { URL.revokeObjectURL(preloadedAudio[name].blobUrl); } catch (e) {}
			delete preloadedAudio[name];
		}
	}

	const loopingByName = new Map(tracks.map(t => [t.filename, t.looping || false]));
	const newTracks = incoming.map(t => ({ ...t, looping: loopingByName.get(t.filename) || false }));

	tracks.length = 0;
	tracks.push(...newTracks);

	if (tracks.length === 0) {
		playerReady = false;
		try { audio.pause(); } catch (e) {}
		audio.removeAttribute('src');
		audio.load();
		isPlaying = false;
		resetProgressBar();
		updatePlayPauseButton();
		updateCurrentTrackDisplay('No tracks found');
		playlist.innerHTML = '';
		return;
	}

	playerReady = true;

	if (playingRemoved) {
		// Playing track is gone: stop, advance to the next-best slot, and
		// drop into "Ready to play".
		try { audio.pause(); } catch (e) {}
		audio.removeAttribute('src');
		audio.load();
		isPlaying = false;
		resetProgressBar();
		const nextIndex = Math.min(currentTrackIndex, tracks.length - 1);
		setCurrentTrackIndex(nextIndex);
		const next = tracks[nextIndex];
		updateCurrentTrackDisplay(`Ready to play: ${next.artist} – ${next.title}`);
		updatePlayPauseButton();
	} else if (playingFilename) {
		// Playing track survived (possibly via a rename applied above): its
		// index may have shifted because of reorders or adds/removes
		// elsewhere in the list.
		const newIndex = tracks.findIndex(t => t.filename === playingFilename);
		if (newIndex !== -1) setCurrentTrackIndex(newIndex);

		const cur = tracks[currentTrackIndex];
		if (cur) {
			const isReady = currentTrackDisplay.textContent.includes('Ready to play:');
			const text = isReady
				? `Ready to play: ${cur.artist} – ${cur.title}`
				: `${cur.artist} – ${cur.title}`;
			updateNowPlayingTextInPlace(text);
		}
	}

	renderPlaylist();

	// Pick up any tracks added since last preload pass.
	if (typeof preloadNextTrack === 'function') {
		currentPreloadIndex = 0;
		preloadNextTrack();
	}
}

function startLiveSync() {
	const source = new EventSource('/events');
	source.addEventListener('tracks', (e) => {
		const payload = JSON.parse(e.data);
		if (!sseSeenInitial) {
			sseSeenInitial = true;
			return;
		}
		reconcileTracks(payload.tracks, payload.renames);
	});
}

startLiveSync();
