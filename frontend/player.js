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
        console.log('Player.play called', { trackId: track.id, contextProvided: !!context });
        // Switch playlist context if provided
        if (context) {
            console.log('Switching playlist context. Length:', context.length);
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
        const index = this.playlist.findIndex(t => t.id === track.id);
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
            if (el.dataset.trackId === track.id) {
                el.classList.add('playing');

                // Manual scroll calculation to prevent whole-page scrolling
                // We find the specific container and scroll ONLY that.
                const container = el.closest('.track-list');
                if (container) {
                    // Simple logic: scroll the container so the element is centered
                    // offsetTop is usually reliable if container is the offsetParent. 
                    // If not, we fall back to bounding client rect diff, but let's try a robust method.

                    const elTop = el.offsetTop;
                    const elHeight = el.offsetHeight;
                    const containerHeight = container.clientHeight;

                    // Desired Scroll Position = (Element Top) - (Half Container Height) + (Half Element Height)
                    // This centers the element
                    const targetScroll = elTop - (containerHeight / 2) + (elHeight / 2);

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
