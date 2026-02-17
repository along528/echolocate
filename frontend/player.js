/**
 * Audio Player Controller
 */

const Player = {
    audio: null,
    currentTrack: null,
    playlist: [],
    currentIndex: -1,
    isPlaying: false,

    init() {
        this.audio = document.getElementById('audio-player');
        this.playBtn = document.getElementById('play-btn');
        this.prevBtn = document.getElementById('prev-btn');
        this.nextBtn = document.getElementById('next-btn');
        this.progressBar = document.getElementById('progress-bar');
        this.currentTimeEl = document.getElementById('current-time');
        this.durationEl = document.getElementById('duration');
        this.nowPlayingTitle = document.getElementById('now-playing-title');
        this.nowPlayingArtist = document.getElementById('now-playing-artist');

        this.setupEventListeners();
        this.setupKeyboardListeners();
        this.restoreState();
    },

    saveState() {
        try {
            const state = {
                playlist: this.playlist,
                currentTrack: this.currentTrack,
                currentIndex: this.currentIndex
            };
            localStorage.setItem('echolocate-player', JSON.stringify(state));
        } catch (e) {
            console.warn('Failed to save player state:', e);
        }
    },

    restoreState() {
        try {
            const raw = localStorage.getItem('echolocate-player');
            if (!raw) return;
            const state = JSON.parse(raw);
            if (state.playlist && state.playlist.length > 0) {
                this.playlist = state.playlist;
                this.currentIndex = state.currentIndex ?? -1;
                if (state.currentTrack) {
                    this.currentTrack = state.currentTrack;
                    this.updateNowPlaying();
                }
            }
        } catch (e) {
            console.warn('Failed to restore player state:', e);
        }
    },

    setupEventListeners() {
        this.playBtn.addEventListener('click', () => this.togglePlay());
        this.prevBtn.addEventListener('click', () => this.prev());
        this.nextBtn.addEventListener('click', () => this.next());

        this.audio.addEventListener('timeupdate', () => this.updateProgress());
        this.audio.addEventListener('loadedmetadata', () => this.updateDuration());
        this.audio.addEventListener('ended', () => this.next());
        this.audio.addEventListener('play', () => this.onPlay());
        this.audio.addEventListener('pause', () => this.onPause());

        this.progressBar.addEventListener('input', (e) => this.seek(e.target.value));
    },

    setupKeyboardListeners() {
        document.addEventListener('keydown', (e) => {
            const tag = e.target.tagName;
            if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

            switch (e.code) {
                case 'Space':
                    e.preventDefault();
                    this.togglePlay();
                    break;
                case 'ArrowLeft':
                    e.preventDefault();
                    this.prev();
                    break;
                case 'ArrowRight':
                    e.preventDefault();
                    this.next();
                    break;
            }
        });
    },

    play(track, context = null) {
        console.log('Player.play called', {
            trackId: track.id,
            contextSize: context ? context.length : 'null'
        });

        // Switch playlist context if provided
        if (context) {
            console.log('Switching playlist context to:', context.map(t => t.id));
            this.playlist = context;
        }

        this.currentTrack = track;
        this.audio.src = API.getStreamUrl(track.id);

        const playPromise = this.audio.play();
        if (playPromise !== undefined) {
            playPromise.catch(error => {
                console.error('Playback failed:', error);
            });
        }

        this.updateNowPlaying();
        this.updateMediaSession(track);
        this.saveState();

        // Sync currentIndex if track is in playlist
        const index = this.playlist.findIndex(t => String(t.id) === String(track.id));
        console.log('Track index in playlist:', index);

        if (index !== -1) {
            this.currentIndex = index;
        } else {
            // Track not in current playlist (e.g. random play from builder or isolated play)
            this.currentIndex = -1;
        }

        // Update playing state in UI
        document.querySelectorAll('.track-item').forEach(el => {
            el.classList.remove('playing');
            if (String(el.dataset.trackId) === String(track.id)) {
                el.classList.add('playing');

                // Manual scroll calculation to prevent whole-page scrolling
                // We find the specific container and scroll ONLY that.
                // Support both search results (.track-list) and builder (.builder-slots)
                const container = el.closest('.track-list, .builder-slots');

                if (container) {
                    // Use getBoundingClientRect for robust calculation regardless of nesting/positioning
                    const elRect = el.getBoundingClientRect();
                    const containerRect = container.getBoundingClientRect();
                    const currentScroll = container.scrollTop;

                    // Calculate position relative to the scrollable content
                    // (Distance from visible top) + (Current Scroll) = Absolute Top
                    const relativeTop = elRect.top - containerRect.top;

                    // Target: Center the element
                    const targetScroll = currentScroll + relativeTop - (container.clientHeight / 2) + (el.clientHeight / 2);

                    container.scrollTo({
                        top: targetScroll,
                        behavior: 'smooth'
                    });
                }
            }
        });
    },

    togglePlay() {
        if (this.audio.paused) {
            this.audio.play();
        } else {
            this.audio.pause();
        }
    },

    prev() {
        if (this.currentIndex > 0) {
            this.currentIndex--;
            this.play(this.playlist[this.currentIndex]);
        }
    },

    next() {
        if (this.currentIndex < this.playlist.length - 1) {
            this.currentIndex++;
            this.play(this.playlist[this.currentIndex]);
        }
    },

    setPlaylist(tracks, startIndex = 0) {
        this.playlist = tracks;
        this.currentIndex = startIndex;
        this.saveState();
        if (tracks.length > 0) {
            this.play(tracks[startIndex]);
        }
    },

    addToPlaylist(track) {
        // Avoid duplicates
        if (!this.playlist.find(t => t.id === track.id)) {
            this.playlist.push(track);
            this.saveState();
            return true;
        }
        return false;
    },

    /**
     * Updates the current playlist without interrupting playback.
     * Useful for dynamic lists like the Builder.
     */
    updatePlaylist(newTracks) {
        if (!newTracks || newTracks.length === 0) return;

        // Check if we are currently playing a track from this list
        // (naive check: is the current track ID present in the new list?)
        if (this.currentTrack) {
            const newIndex = newTracks.findIndex(t => String(t.id) === String(this.currentTrack.id));
            if (newIndex !== -1) {
                // Yes, current track is still here. Safe to update.
                console.log('Syncing playlist. Current track moved to index:', newIndex);
                this.playlist = newTracks;
                this.currentIndex = newIndex;
            } else {
                // Current track not in new list.
                // Decision: Do we update anyway?
                // If we do, currentIndex becomes invalid (-1), next user action will restart.
                // This seems correct for "Builder changed significantly".
                console.log('Syncing playlist. Current track not found in new list.');
                this.playlist = newTracks;
                this.currentIndex = -1;
            }
        } else {
            // Not playing, just update
            this.playlist = newTracks;
            this.currentIndex = -1;
        }
        this.saveState();
    },

    clearPlaylist() {
        this.playlist = [];
        this.currentIndex = -1;
        this.audio.pause();
        this.audio.src = '';
        this.nowPlayingTitle.textContent = 'No track playing';
        this.nowPlayingArtist.textContent = '';
    },

    updateProgress() {
        if (this.audio.duration) {
            const progress = (this.audio.currentTime / this.audio.duration) * 100;
            this.progressBar.value = progress;
            this.currentTimeEl.textContent = this.formatTime(this.audio.currentTime);
        }
    },

    updateDuration() {
        this.durationEl.textContent = this.formatTime(this.audio.duration);
    },

    seek(value) {
        if (this.audio.duration) {
            this.audio.currentTime = (value / 100) * this.audio.duration;
        }
    },

    updateMediaSession(track) {
        if ('mediaSession' in navigator) {
            navigator.mediaSession.metadata = new MediaMetadata({
                title: track.title,
                artist: track.artist,
                album: track.album || ''
            });
            navigator.mediaSession.setActionHandler('play', () => this.audio.play());
            navigator.mediaSession.setActionHandler('pause', () => this.audio.pause());
            navigator.mediaSession.setActionHandler('previoustrack', () => this.prev());
            navigator.mediaSession.setActionHandler('nexttrack', () => this.next());
        }
    },

    updateNowPlaying() {
        if (this.currentTrack) {
            this.nowPlayingTitle.textContent = this.currentTrack.title;
            this.nowPlayingArtist.textContent = this.currentTrack.artist;
        }
    },

    onPlay() {
        this.isPlaying = true;
        this.playBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="currentColor" width="20" height="20"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>';
    },

    onPause() {
        this.isPlaying = false;
        this.playBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="currentColor" width="20" height="20"><path d="M8 5v14l11-7z"/></svg>';
    },

    formatTime(seconds) {
        if (!seconds || isNaN(seconds)) return '0:00';
        const mins = Math.floor(seconds / 60);
        const secs = Math.floor(seconds % 60);
        return `${mins}:${secs.toString().padStart(2, '0')}`;
    }
};
