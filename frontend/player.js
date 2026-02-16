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
        if (tracks.length > 0) {
            this.play(tracks[startIndex]);
        }
    },

    addToPlaylist(track) {
        // Avoid duplicates
        if (!this.playlist.find(t => t.id === track.id)) {
            this.playlist.push(track);
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

    updateNowPlaying() {
        if (this.currentTrack) {
            this.nowPlayingTitle.textContent = this.currentTrack.title;
            this.nowPlayingArtist.textContent = this.currentTrack.artist;
        }
    },

    onPlay() {
        this.isPlaying = true;
        this.playBtn.textContent = '⏸';
    },

    onPause() {
        this.isPlaying = false;
        this.playBtn.textContent = '▶';
    },

    formatTime(seconds) {
        if (!seconds || isNaN(seconds)) return '0:00';
        const mins = Math.floor(seconds / 60);
        const secs = Math.floor(seconds % 60);
        return `${mins}:${secs.toString().padStart(2, '0')}`;
    }
};
