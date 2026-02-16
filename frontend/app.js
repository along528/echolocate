/**
 * Main Application Logic
 */

const App = {
    searchMode: 'semantic',
    enhanceQuery: true,
    results: [],
    pinnedTrack: null,

    // Interpolation Builder State
    startTrack: null,
    middleTrack: null,
    endTrack: null,
    generatedPlaylist: [],

    init() {
        Player.init();
        this.setupEventListeners();
        this.setupDragAndDrop();
        this.loadInitialTracks();
        this.updateUIState(); // Ensure initial state is correct
    },

    setupEventListeners() {
        // Search tabs
        document.querySelectorAll('.tab').forEach(tab => {
            tab.addEventListener('click', (e) => {
                const target = e.currentTarget;
                document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
                target.classList.add('active');
                this.searchMode = target.dataset.tab;
                this.updateUIState();
            });
        });

        // Search
        document.getElementById('search-btn').addEventListener('click', () => this.search());
        document.getElementById('search-input').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.search();
        });

        // Enhanced Query Toggle
        const toggle = document.getElementById('enhance-toggle');
        if (toggle) {
            toggle.addEventListener('change', (e) => {
                this.enhanceQuery = e.target.checked;
            });
        }

        // Builder controls
        document.getElementById('clear-builder').addEventListener('click', () => {
            this.startTrack = null;
            this.middleTrack = null;
            this.endTrack = null;
            this.generatedPlaylist = [];
            Player.playlist = [];
            this.renderBuilder();
            // Ensure we are in builder view
            document.getElementById('builder-view').style.display = 'block';
            document.getElementById('playlist-view').style.display = 'none';
        });

        // Reset / Back to Builder
        document.getElementById('reset-builder').addEventListener('click', () => {
            document.getElementById('builder-view').style.display = 'block';
            document.getElementById('playlist-view').style.display = 'none';
        });

        const interpolateBtn = document.getElementById('interpolate-btn');
        if (interpolateBtn) {
            interpolateBtn.addEventListener('click', () => this.interpolate());
        }

        document.getElementById('random-btn').addEventListener('click', () => this.loadInitialTracks());
        document.getElementById('clear-results').addEventListener('click', () => this.clearResults());

        // Slot clearing
        const clearMidBtn = document.querySelector('#slot-middle .clear-slot-btn');
        if (clearMidBtn) {
            clearMidBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.middleTrack = null;
                this.renderBuilder();
            });
        }
    },

    updateUIState() {
        // Update placeholder
        const placeholder = this.searchMode === 'semantic'
            ? 'Describe the vibe (e.g., "warm jazz saxophone", "energetic electronic")...'
            : 'Search by artist, title, or album...';
        document.getElementById('search-input').placeholder = placeholder;

        // Toggle semantic options
        const semanticOptions = document.getElementById('semantic-options');
        const enhancedDisplay = document.getElementById('enhanced-query-display');

        if (semanticOptions) {
            if (this.searchMode === 'semantic') {
                semanticOptions.style.display = 'block';
            } else {
                semanticOptions.style.display = 'none';
                // Hide results display when switching modes
                if (enhancedDisplay) {
                    enhancedDisplay.style.visibility = 'hidden';
                    enhancedDisplay.style.opacity = '0';
                }
            }
        }
    },

    setupDragAndDrop() {
        const slots = {
            'slot-start': 'setStartTrack',
            'slot-middle': 'setMiddleTrack',
            'slot-end': 'setEndTrack'
        };

        Object.entries(slots).forEach(([id, method]) => {
            const el = document.getElementById(id);
            if (!el) return;

            el.addEventListener('dragover', (e) => {
                e.preventDefault(); // Allow drop
                e.dataTransfer.dropEffect = 'copy';
                el.classList.add('drag-over');
            });

            el.addEventListener('dragleave', () => {
                el.classList.remove('drag-over');
            });

            el.addEventListener('drop', (e) => {
                e.preventDefault();
                el.classList.remove('drag-over');
                try {
                    const track = JSON.parse(e.dataTransfer.getData('text/plain'));
                    if (track && track.id) {
                        // Use the setter method to ensure side effects (like removal from results) happen
                        this[method](track);
                    }
                } catch (err) {
                    console.error('Drop failed:', err);
                }
            });
        });
    },

    addTrackToBuilder(track) {
        // Smart Add Logic:
        // 1. If Start is empty -> Set Start
        // 2. If End is empty -> Set End
        // 3. If both set -> Shift: Start(keeps), End->Middle, New->End

        if (!this.startTrack) {
            this.startTrack = track;
        } else if (!this.endTrack) {
            this.endTrack = track;
        } else {
            // Both start and end are set.
            // Move current End to Middle (replacing whatever was there)
            this.middleTrack = this.endTrack;
            // Set new track as End
            this.endTrack = track;
        }
        this.renderBuilder();
    },

    async loadInitialTracks() {
        try {
            const source = this.getSelectedSource();
            const tracks = await API.getTracks(50, source);
            this.results = tracks;
            this.pinnedTrack = null;
            this.renderResults();
            document.getElementById('result-count').textContent = `(${tracks.length} random)`;
        } catch (error) {
            console.error('Failed to load tracks:', error);
        }
    },

    clearResults() {
        this.results = [];
        this.pinnedTrack = null;
        this.renderResults();
        document.getElementById('result-count').textContent = '';
    },

    async search() {
        const query = document.getElementById('search-input').value.trim();
        if (!query) return;

        const source = this.getSelectedSource();
        const enhancedDisplay = document.getElementById('enhanced-query-display');
        enhancedDisplay.style.visibility = 'hidden';
        enhancedDisplay.style.opacity = '0';

        try {
            let tracks;
            if (this.searchMode === 'semantic') {
                const response = await API.semanticSearch(query, source, 50, this.enhanceQuery);

                // Handle new response structure { results: [...], enhanced_query: "..." }
                if (response.results) {
                    tracks = response.results;

                    if (response.enhanced_query && this.enhanceQuery) {
                        enhancedDisplay.innerHTML = `<strong>Enhanced:</strong> "${response.enhanced_query}"`;
                        enhancedDisplay.style.visibility = 'visible';
                        enhancedDisplay.style.opacity = '1';
                    } else {
                        enhancedDisplay.style.visibility = 'hidden';
                        enhancedDisplay.style.opacity = '0';
                    }
                } else {
                    // Fallback if backend returns direct array (backward compatibility)
                    tracks = response;
                }
            } else {
                tracks = await API.textSearch(query, source);
            }

            this.results = tracks;
            this.renderResults();
            document.getElementById('result-count').textContent = `(${tracks.length} found)`;
        } catch (error) {
            console.error('Search failed:', error);
        }
    },

    async findSimilar(track, source = 'fma') {
        const selectedSource = this.getSelectedSource();
        try {
            const tracks = await API.findSimilar(track.id, selectedSource);
            this.results = tracks;
            this.pinnedTrack = track;
            this.renderResults();
            document.getElementById('result-count').textContent = `(${tracks.length} similar)`;
        } catch (error) {
            console.error('Find similar failed:', error);
        }
    },

    async findDissimilar(track, source = 'fma') {
        const selectedSource = this.getSelectedSource();
        try {
            const tracks = await API.findDissimilar(track.id, selectedSource);
            this.results = tracks;
            this.pinnedTrack = track;
            this.renderResults();
            document.getElementById('result-count').textContent = `(${tracks.length} dissimilar)`;
        } catch (error) {
            console.error('Find dissimilar failed:', error);
        }
    },

    // Track Management Logic
    removeTrackFromResults(trackId) {
        if (!this.results) return;

        // Find if track exists in results
        const index = this.results.findIndex(t => t.id === trackId);
        if (index !== -1) {
            this.results.splice(index, 1);
            this.renderResults();
            document.getElementById('result-count').textContent = `(${this.results.length})`;
        }
    },

    addTrackToResults(track) {
        if (!track || !this.results) return;

        // Check if already exists to avoid dupes
        if (!this.results.find(t => t.id === track.id)) {
            // Add to beginning
            this.results.unshift(track);
            this.renderResults();
            document.getElementById('result-count').textContent = `(${this.results.length})`;
        }
    },

    setStartTrack(track) {
        // If replacing, put old one back
        if (this.startTrack) {
            this.addTrackToResults(this.startTrack);
        }

        this.startTrack = track;
        this.removeTrackFromResults(track.id);
        this.renderBuilder();
    },

    setMiddleTrack(track) {
        if (this.middleTrack) {
            this.addTrackToResults(this.middleTrack);
        }
        this.middleTrack = track;
        this.removeTrackFromResults(track.id);
        this.renderBuilder();
    },

    setEndTrack(track) {
        if (this.endTrack) {
            this.addTrackToResults(this.endTrack);
        }
        this.endTrack = track;
        this.removeTrackFromResults(track.id);
        this.renderBuilder();
    },

    async interpolate() {
        if (!this.startTrack || !this.endTrack) {
            alert('Please select both a Start and End track.');
            return;
        }

        const btn = document.getElementById('interpolate-btn');
        const originalText = btn.textContent;
        btn.disabled = true;
        btn.textContent = 'Generating...';

        try {
            const source = this.getSelectedSource();
            const steerId = this.middleTrack ? this.middleTrack.id : null;

            const tracks = await API.interpolatePlaylist(
                this.startTrack.id,
                this.endTrack.id,
                10,
                'greedy_walk',
                source,
                steerId
            );

            // Mark tracks
            tracks[0].isStart = true;
            tracks[tracks.length - 1].isEnd = true;
            if (steerId) {
                // Find and mark middle track
                const mid = tracks.find(t => t.id === steerId);
                if (mid) mid.isMiddle = true;
            }

            this.generatedPlaylist = tracks;
            Player.playlist = tracks;
            this.renderPlaylist();

            // Switch View
            document.getElementById('builder-view').style.display = 'none';
            document.getElementById('playlist-view').style.display = 'block';

        } catch (error) {
            console.error('Interpolation failed:', error);
            alert('Failed to generate playlist. See console for details.');
        } finally {
            btn.disabled = false;
            btn.textContent = originalText;
        }
    },

    getSelectedSource() {
        return document.querySelector('input[name="source"]:checked').value;
    },

    renderResults() {
        const container = document.getElementById('results-list');
        container.innerHTML = '';

        if (this.pinnedTrack) {
            const pinnedContainer = document.createElement('div');
            pinnedContainer.className = 'pinned-track-container';
            pinnedContainer.innerHTML = '<h3 class="pinned-label">Reference Track</h3>';
            pinnedContainer.appendChild(Components.renderTrack(this.pinnedTrack, { hideSimilar: true }));
            container.appendChild(pinnedContainer);

            const separator = document.createElement('div');
            separator.className = 'results-separator';
            separator.innerHTML = '<h3>Similar Tracks</h3>';
            container.appendChild(separator);
        }

        Components.renderTrackList(container, this.results, { clear: false });
    },

    renderBuilder() {
        const renderSlot = (track, elementId) => {
            const el = document.getElementById(elementId);
            if (track) {
                el.classList.remove('empty');
                el.classList.add('filled');
                el.innerHTML = '';
                // Use minimal: true to show Play/Link but hide Add/Remove
                // ShowActions: true is needed to show Play/Link
                el.appendChild(Components.renderTrack(track, { showActions: true, minimal: true }));

                if (elementId === 'slot-middle') {
                    const btn = document.createElement('button');
                    btn.className = 'clear-slot-btn';
                    btn.textContent = '×';
                    btn.onclick = (e) => {
                        e.stopPropagation();
                        this.middleTrack = null;
                        this.renderBuilder();
                    };
                    el.appendChild(btn);
                }
            } else {
                el.classList.add('empty');
                el.classList.remove('filled');
                const placeholder = elementId === 'slot-start' ? 'Select a track and click "Set Start"' :
                    elementId === 'slot-middle' ? 'Select a track and click "Set Mid"' :
                        'Select a track and click "Set End"';
                el.innerHTML = `<span class=\"placeholder\">${placeholder}</span>`;

                if (elementId === 'slot-middle') {
                    const btn = document.createElement('button');
                    btn.className = 'clear-slot-btn';
                    btn.textContent = '×';
                    btn.onclick = (e) => {
                        e.stopPropagation();
                        this.middleTrack = null;
                        this.renderBuilder();
                    };
                    el.appendChild(btn);
                }
            }
        };

        renderSlot(this.startTrack, 'slot-start');
        renderSlot(this.middleTrack, 'slot-middle');
        renderSlot(this.endTrack, 'slot-end');

        // Enable interpolate button if we have start and end
        const interpolateBtn = document.getElementById('interpolate-btn');
        if (interpolateBtn) {
            interpolateBtn.disabled = !(this.startTrack && this.endTrack);
        }
    },

    renderPlaylist() {
        const container = document.getElementById('playlist');
        Components.renderTrackList(container, this.generatedPlaylist, { inPlaylist: true });
    }
};

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => App.init());
