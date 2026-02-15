/**
 * Main Application Logic
 */

const App = {
    searchMode: 'semantic',
    enhanceQuery: true,
    results: [],
    pinnedTrack: null,

    // Interpolation Builder State
    slots: {
        start: { id: 'start', track: null, query: '', results: [], currentIndex: -1, enhancedQuery: null },
        middle: { id: 'middle', track: null, query: '', results: [], currentIndex: -1, enhancedQuery: null },
        end: { id: 'end', track: null, query: '', results: [], currentIndex: -1, enhancedQuery: null }
    },
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
            this.resetSlots();
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

        // Setup listeners for each slot
        this.setupSlotListeners('start');
        this.setupSlotListeners('middle');
        this.setupSlotListeners('end');
    },

    setupSlotListeners(slotName) {
        const container = document.querySelector(`.slot-container[data-slot="${slotName}"]`);
        if (!container) return;

        const input = container.querySelector('.slot-search-input');
        const prevBtn = container.querySelector('.slot-nav-btn.prev');
        const nextBtn = container.querySelector('.slot-nav-btn.next');
        const clearBtn = container.querySelector('.clear-slot-btn-main'); // For middle slot

        if (input) {
            input.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') {
                    this.handleSlotSearch(slotName, input.value);
                }
            });
            // Update query state on blur or input
            input.addEventListener('input', (e) => {
                this.slots[slotName].query = e.target.value;
            });
        }

        if (prevBtn) {
            prevBtn.addEventListener('click', () => this.navigateSlot(slotName, -1));
        }

        if (nextBtn) {
            nextBtn.addEventListener('click', () => this.navigateSlot(slotName, 1));
        }

        if (clearBtn) {
            clearBtn.addEventListener('click', () => {
                this.resetSlot(slotName);
                this.renderBuilder();
            });
        }
    },

    resetSlots() {
        ['start', 'middle', 'end'].forEach(slot => this.resetSlot(slot));
    },

    resetSlot(slotName) {
        this.slots[slotName] = {
            id: slotName,
            track: null,
            query: '',
            results: [],
            currentIndex: -1,
            enhancedQuery: null
        };
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
        // Map slot IDs (container IDs or drop zones) to logic
        const slots = ['start', 'middle', 'end'];

        slots.forEach(slotName => {
            // The drop zone is the track-slot div
            const el = document.querySelector(`.slot-container[data-slot="${slotName}"] .track-slot`);
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
                        this.setSlotTrack(slotName, track);
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

        if (!this.slots.start.track) {
            this.setSlotTrack('start', track);
        } else if (!this.slots.end.track) {
            this.setSlotTrack('end', track);
        } else {
            // Move current End to Middle
            this.setSlotTrack('middle', this.slots.end.track);
            // Set new track as End
            this.setSlotTrack('end', track);
        }
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

    setSlotTrack(slotName, track) {
        const slot = this.slots[slotName];
        if (slot.track) {
            this.addTrackToResults(slot.track);
        }
        slot.track = track;
        // Optimization: When explicitly setting a track (drag/drop), should we clear the query?
        // User requirements say "This information [query] should be retained...".
        // But if I drag a track, the query might not match the track. 
        // Let's keep the query if it exists, but maybe update the input placeholder?
        // For now, we won't clear the query, but we might hide it visually or it just sits there.

        this.removeTrackFromResults(track.id);
        this.renderBuilder();
    },

    async handleSlotSearch(slotName, query) {
        if (!query) return;
        const slot = this.slots[slotName];
        slot.query = query;

        // Visual feedback (loading?) - for now just rely on speed
        const container = document.querySelector(`.slot-container[data-slot="${slotName}"]`);
        const input = container.querySelector('.slot-search-input');
        input.disabled = true;

        try {
            // Always use semantic with enhancement for slots? Or follow global mode?
            // "flow... support specifying a semantic search query directly... optionally fetch"
            // Let's use semantic search by default for slots as implied by "semantic search query"
            const source = this.getSelectedSource();
            // We'll ask for fewer results for slots, maybe 10?
            const response = await API.semanticSearch(query, source, 10, true);

            let tracks = [];
            if (response.results) {
                tracks = response.results;
                slot.enhancedQuery = response.enhanced_query;
            } else {
                tracks = response;
                slot.enhancedQuery = null;
            }

            if (tracks.length > 0) {
                slot.results = tracks;
                slot.currentIndex = 0;
                slot.track = tracks[0];
                // Do NOT remove this local result from the global results list automatically
                // But we should probably not remove it from the slot's own results list either.
            } else {
                slot.results = [];
                slot.track = null;
            }
        } catch (e) {
            console.error(`Search for slot ${slotName} failed:`, e);
        } finally {
            input.disabled = false;
            input.focus();
            this.renderBuilder();
        }
    },

    navigateSlot(slotName, direction) {
        const slot = this.slots[slotName];
        if (!slot.results || slot.results.length === 0) return;

        let newIndex = slot.currentIndex + direction;
        if (newIndex < 0) newIndex = slot.results.length - 1;
        if (newIndex >= slot.results.length) newIndex = 0;

        slot.currentIndex = newIndex;
        slot.track = slot.results[newIndex];
        this.renderBuilder();
    },

    async interpolate() {
        // Check if we have tracks or pending queries
        const startReady = this.slots.start.track || this.slots.start.query;
        const endReady = this.slots.end.track || this.slots.end.query;

        if (!startReady || !endReady) {
            alert('Please select both a Start and End track (or enter a query).');
            return;
        }

        const btn = document.getElementById('interpolate-btn');
        const originalText = btn.textContent;
        btn.disabled = true;
        btn.textContent = 'Generating...';

        try {
            // Resolve Deferred Searches
            const resolveSlot = async (slotName) => {
                const slot = this.slots[slotName];
                if (!slot.track && slot.query) {
                    // Perform deferred search
                    console.log(`Resolving deferred search for ${slotName}: ${slot.query}`);
                    await this.handleSlotSearch(slotName, slot.query);
                    if (!slot.track) throw new Error(`Could not find track for query: "${slot.query}"`);
                }
                return slot.track;
            };

            const startTrack = await resolveSlot('start');
            const endTrack = await resolveSlot('end');

            // Middle is optional
            let middleTrack = this.slots.middle.track;
            if (!middleTrack && this.slots.middle.query) {
                await this.handleSlotSearch('middle', this.slots.middle.query);
                middleTrack = this.slots.middle.track;
            }

            const source = this.getSelectedSource();
            const steerId = middleTrack ? middleTrack.id : null;

            const tracks = await API.interpolatePlaylist(
                startTrack.id,
                endTrack.id,
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

            // Add query info to the result display if meaningful?
            // "This information should be retained when generating the playlist but is display only"
            // We'll leave it in the builder view state.

            this.generatedPlaylist = tracks;
            Player.playlist = tracks;
            this.renderPlaylist();

            // Switch View
            document.getElementById('builder-view').style.display = 'none';
            document.getElementById('playlist-view').style.display = 'block';

        } catch (error) {
            console.error('Interpolation failed:', error);
            alert(`Failed to generate: ${error.message}`);
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
        ['start', 'middle', 'end'].forEach(slotName => {
            const slot = this.slots[slotName];
            const container = document.querySelector(`.slot-container[data-slot="${slotName}"]`);
            if (!container) return;

            // UI Elements
            const input = container.querySelector('.slot-search-input');
            const navControls = container.querySelector('.slot-nav-controls');
            const navCount = container.querySelector('.slot-nav-count');
            const enhancedDisplay = container.querySelector('.slot-enhanced-query');
            const trackSlot = container.querySelector('.track-slot');
            const prevBtn = container.querySelector('.slot-nav-btn.prev');
            const nextBtn = container.querySelector('.slot-nav-btn.next');
            const clearBtn = container.querySelector('.clear-slot-btn-main'); // Middle slot only

            // Update Input Value if it differs?
            // Only if input is not focused to avoid messing up typing?
            // Actually, we want the input to reflect the state 'query'.
            if (document.activeElement !== input) {
                input.value = slot.query;
            }

            // Update Enhanced Query Display
            if (slot.enhancedQuery) {
                enhancedDisplay.style.display = 'block';
                enhancedDisplay.textContent = `✨ ${slot.enhancedQuery}`;
                enhancedDisplay.title = slot.enhancedQuery;
            } else {
                enhancedDisplay.style.display = 'none';
            }

            // Update Nav Controls
            if (slot.results.length > 1) {
                navControls.style.display = 'flex';
                navCount.textContent = `${slot.currentIndex + 1}/${slot.results.length}`;
                prevBtn.disabled = false; // Circular nav
                nextBtn.disabled = false;
            } else {
                navControls.style.display = 'none';
            }

            // Middle slot clear button
            if (clearBtn) {
                clearBtn.style.display = (slot.track || slot.query) ? 'block' : 'none';
            }

            // Render Track Slot
            if (slot.track) {
                trackSlot.classList.remove('empty');
                trackSlot.classList.add('filled');
                trackSlot.innerHTML = '';
                // Render with 'minimal' + 'showActions'
                trackSlot.appendChild(Components.renderTrack(slot.track, { showActions: true, minimal: true }));

                // We removed the inner 'X' button in HTML, relying on main clear button or just replacing
            } else {
                trackSlot.classList.add('empty');
                trackSlot.classList.remove('filled');
                const placeholder = slotName === 'start' ? 'Drag track here or type above' :
                    slotName === 'middle' ? 'Drag track here or type above' :
                        'Drag track here or type above';
                trackSlot.innerHTML = `<span class=\"placeholder\">${placeholder}</span>`;
            }
        });

        // Enable interpolate button
        const interpolateBtn = document.getElementById('interpolate-btn');
        if (interpolateBtn) {
            // Enabled if start/end have track OR query
            const startReady = this.slots.start.track || this.slots.start.query;
            const endReady = this.slots.end.track || this.slots.end.query;
            interpolateBtn.disabled = !(startReady && endReady);
        }
    },

    renderPlaylist() {
        const container = document.getElementById('playlist');
        Components.renderTrackList(container, this.generatedPlaylist, { inPlaylist: true });
    }
};

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => App.init());
