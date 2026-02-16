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
        end: { id: 'end', track: null, query: '', results: [], currentIndex: -1, enhancedQuery: null }
    },
    steerSlots: [],
    steerCounter: 0,
    generatedPlaylist: [],

    init() {
        Player.init();
        this.setupEventListeners();
        this.setupDragAndDrop();
        this.loadInitialTracks();
        this.updateUIState();
        this.renderBuilder();
    },

    getSlot(name) {
        if (this.slots[name]) return this.slots[name];
        return this.steerSlots.find(s => s.id === name) || null;
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

        // Setup listeners for fixed slots
        this.setupSlotListeners('start');
        this.setupSlotListeners('end');

        // Initial insert buttons rendered on first renderBuilder call
    },

    setupSlotListeners(slotName) {
        const container = document.querySelector(`.slot-container[data-slot="${slotName}"]`);
        if (!container) return;

        const input = container.querySelector('.slot-search-input');
        const prevBtn = container.querySelector('.slot-nav-btn.prev');
        const nextBtn = container.querySelector('.slot-nav-btn.next');
        const clearBtn = container.querySelector('.clear-slot-btn-main');

        if (input) {
            input.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') {
                    this.handleSlotSearch(slotName, input.value);
                }
            });
            input.addEventListener('input', (e) => {
                const slot = this.getSlot(slotName);
                if (slot) slot.query = e.target.value;
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

    addSteerSlot(track = null, insertIndex = -1) {
        const slotId = `steer-${this.steerCounter++}`;
        const slotState = {
            id: slotId,
            track: track || null,
            query: '',
            results: [],
            currentIndex: -1,
            enhancedQuery: null
        };

        // Insert at position or append
        if (insertIndex >= 0 && insertIndex < this.steerSlots.length) {
            this.steerSlots.splice(insertIndex, 0, slotState);
        } else {
            this.steerSlots.push(slotState);
        }

        // Build DOM element and insert at correct position in container
        const el = this.createSteerSlotElement(slotId);
        const container = document.getElementById('steer-slots-container');
        const existingSlots = container.querySelectorAll('.slot-container');
        const domIndex = this.steerSlots.findIndex(s => s.id === slotId);
        if (domIndex < existingSlots.length) {
            container.insertBefore(el, existingSlots[domIndex]);
        } else {
            container.appendChild(el);
        }

        // Bind listeners and drag/drop
        this.setupSlotListeners(slotId);
        this.setupSlotDragDrop(slotId);

        if (track) {
            this.removeTrackFromResults(track.id);
        }

        this.renderBuilder();
        return slotId;
    },

    createSteerSlotElement(slotId) {
        const div = document.createElement('div');
        div.className = 'slot-container steer-slot-container';
        div.dataset.slot = slotId;
        div.innerHTML = `
            <div class="slot-input-wrapper">
                <input type="text" class="slot-search-input" placeholder="Search or drag track..."
                    autocomplete="off">
                <div class="slot-nav-controls" style="display: none;">
                    <button class="slot-nav-btn prev" title="Previous result">←</button>
                    <span class="slot-nav-count"></span>
                    <button class="slot-nav-btn next" title="Next result">→</button>
                </div>
            </div>
            <div class="slot-enhanced-query" style="display: none;"></div>
            <div class="track-slot empty">
                <span class="placeholder">Drag track here or type above</span>
                <button class="remove-steer-btn" title="Remove">×</button>
            </div>
        `;

        div.querySelector('.remove-steer-btn').addEventListener('click', (e) => {
            e.stopPropagation();
            this.removeSteerSlot(slotId);
        });

        return div;
    },

    removeSteerSlot(slotId) {
        const index = this.steerSlots.findIndex(s => s.id === slotId);
        if (index === -1) return;

        const slot = this.steerSlots[index];
        if (slot.track) {
            this.addTrackToResults(slot.track);
        }

        this.steerSlots.splice(index, 1);

        // Remove DOM
        const el = document.querySelector(`.slot-container[data-slot="${slotId}"]`);
        if (el) el.remove();

        this.renderBuilder();
    },

    resetSlots() {
        ['start', 'end'].forEach(slot => this.resetSlot(slot));
        // Remove all steer slots
        this.steerSlots.forEach(s => {
            const el = document.querySelector(`.slot-container[data-slot="${s.id}"]`);
            if (el) el.remove();
        });
        this.steerSlots = [];
    },

    resetSlot(slotName) {
        const slot = this.getSlot(slotName);
        if (!slot) return;
        slot.track = null;
        slot.query = '';
        slot.results = [];
        slot.currentIndex = -1;
        slot.enhancedQuery = null;
    },

    updateUIState() {
        const placeholder = this.searchMode === 'semantic'
            ? 'Describe the vibe (e.g., "warm jazz saxophone", "energetic electronic")...'
            : 'Search by artist, title, or album...';
        document.getElementById('search-input').placeholder = placeholder;

        const semanticOptions = document.getElementById('semantic-options');
        const enhancedDisplay = document.getElementById('enhanced-query-display');

        if (semanticOptions) {
            if (this.searchMode === 'semantic') {
                semanticOptions.style.display = 'block';
            } else {
                semanticOptions.style.display = 'none';
                if (enhancedDisplay) {
                    enhancedDisplay.style.visibility = 'hidden';
                    enhancedDisplay.style.opacity = '0';
                }
            }
        }
    },

    setupDragAndDrop() {
        ['start', 'end'].forEach(slotName => this.setupSlotDragDrop(slotName));
    },

    setupSlotDragDrop(slotName) {
        const el = document.querySelector(`.slot-container[data-slot="${slotName}"] .track-slot`);
        if (!el) return;

        el.addEventListener('dragover', (e) => {
            e.preventDefault();
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
    },

    addTrackToBuilder(track) {
        // Smart Add: start -> end -> push old end into new steer slot, set new as end
        if (!this.slots.start.track) {
            this.setSlotTrack('start', track);
        } else if (!this.slots.end.track) {
            this.setSlotTrack('end', track);
        } else {
            // Push current end into a new steering slot
            this.addSteerSlot(this.slots.end.track);
            // Set new track as end (don't return old end to results since addSteerSlot consumed it)
            this.slots.end.track = track;
            this.removeTrackFromResults(track.id);
            this.renderBuilder();
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

    removeTrackFromResults(trackId) {
        if (!this.results) return;
        const index = this.results.findIndex(t => t.id === trackId);
        if (index !== -1) {
            this.results.splice(index, 1);
            this.renderResults();
            document.getElementById('result-count').textContent = `(${this.results.length})`;
        }
    },

    addTrackToResults(track) {
        if (!track || !this.results) return;
        if (!this.results.find(t => t.id === track.id)) {
            this.results.unshift(track);
            this.renderResults();
            document.getElementById('result-count').textContent = `(${this.results.length})`;
        }
    },

    setSlotTrack(slotName, track) {
        const slot = this.getSlot(slotName);
        if (!slot) return;
        if (slot.track) {
            this.addTrackToResults(slot.track);
        }
        slot.track = track;
        this.removeTrackFromResults(track.id);
        this.renderBuilder();
    },

    async handleSlotSearch(slotName, query) {
        if (!query) return;
        const slot = this.getSlot(slotName);
        if (!slot) return;
        slot.query = query;

        const container = document.querySelector(`.slot-container[data-slot="${slotName}"]`);
        const input = container.querySelector('.slot-search-input');
        input.disabled = true;

        try {
            const source = this.getSelectedSource();
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
        const slot = this.getSlot(slotName);
        if (!slot || !slot.results || slot.results.length === 0) return;

        let newIndex = slot.currentIndex + direction;
        if (newIndex < 0) newIndex = slot.results.length - 1;
        if (newIndex >= slot.results.length) newIndex = 0;

        slot.currentIndex = newIndex;
        slot.track = slot.results[newIndex];
        this.renderBuilder();
    },

    async interpolate() {
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
            // Resolve deferred searches
            const resolveSlot = async (slotName) => {
                const slot = this.getSlot(slotName);
                if (!slot.track && slot.query) {
                    await this.handleSlotSearch(slotName, slot.query);
                    if (!slot.track) throw new Error(`Could not find track for query: "${slot.query}"`);
                }
                return slot.track;
            };

            const startTrack = await resolveSlot('start');
            const endTrack = await resolveSlot('end');

            // Resolve all steering slots
            const steerTrackIds = [];
            for (const steerSlot of this.steerSlots) {
                if (!steerSlot.track && steerSlot.query) {
                    await this.handleSlotSearch(steerSlot.id, steerSlot.query);
                }
                if (steerSlot.track) {
                    steerTrackIds.push(steerSlot.track.id);
                }
            }

            const source = this.getSelectedSource();

            const tracks = await API.interpolatePlaylist(
                startTrack.id,
                endTrack.id,
                10,
                'greedy_walk',
                source,
                steerTrackIds
            );

            // Mark tracks
            tracks[0].isStart = true;
            tracks[tracks.length - 1].isEnd = true;
            // Mark steering tracks
            const steerIdSet = new Set(steerTrackIds);
            tracks.forEach(t => {
                if (steerIdSet.has(t.id)) t.isSteering = true;
            });

            this.generatedPlaylist = tracks;
            Player.playlist = tracks;
            this.renderPlaylist();

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
        // Render fixed slots (start, end)
        ['start', 'end'].forEach(slotName => this.renderSlot(slotName));
        // Render dynamic steer slots
        this.steerSlots.forEach(s => this.renderSlot(s.id));
        // Render "+" insert buttons between every pair of adjacent slots
        this.renderInsertButtons();

        // Enable interpolate button
        const interpolateBtn = document.getElementById('interpolate-btn');
        if (interpolateBtn) {
            const startReady = this.slots.start.track || this.slots.start.query;
            const endReady = this.slots.end.track || this.slots.end.query;
            interpolateBtn.disabled = !(startReady && endReady);
        }
    },

    renderInsertButtons() {
        // Remove existing insert buttons
        document.querySelectorAll('.insert-steer-btn').forEach(el => el.remove());

        const container = document.getElementById('steer-slots-container');

        const createInsertBtn = (index) => {
            const btn = document.createElement('button');
            btn.className = 'insert-steer-btn';
            btn.textContent = '+';
            btn.title = 'Add track';
            btn.addEventListener('click', () => this.addSteerSlot(null, index));
            return btn;
        };

        // Insert a "+" before each steer slot and one after the last
        const slotElements = container.querySelectorAll('.slot-container');
        if (slotElements.length === 0) {
            // No steer slots yet — just one "+" button
            container.appendChild(createInsertBtn(0));
        } else {
            // Before each steer slot
            slotElements.forEach((el, i) => {
                el.before(createInsertBtn(i));
            });
            // After the last steer slot
            slotElements[slotElements.length - 1].after(createInsertBtn(slotElements.length));
        }
    },

    renderSlot(slotName) {
        const slot = this.getSlot(slotName);
        const container = document.querySelector(`.slot-container[data-slot="${slotName}"]`);
        if (!container || !slot) return;

        const input = container.querySelector('.slot-search-input');
        const navControls = container.querySelector('.slot-nav-controls');
        const navCount = container.querySelector('.slot-nav-count');
        const enhancedDisplay = container.querySelector('.slot-enhanced-query');
        const trackSlot = container.querySelector('.track-slot');
        const prevBtn = container.querySelector('.slot-nav-btn.prev');
        const nextBtn = container.querySelector('.slot-nav-btn.next');
        const clearBtn = container.querySelector('.clear-slot-btn-main');

        if (document.activeElement !== input) {
            input.value = slot.query;
        }

        if (slot.enhancedQuery) {
            enhancedDisplay.style.display = 'block';
            enhancedDisplay.textContent = `✨ ${slot.enhancedQuery}`;
            enhancedDisplay.title = slot.enhancedQuery;
        } else {
            enhancedDisplay.style.display = 'none';
        }

        if (slot.results.length > 1) {
            navControls.style.display = 'flex';
            navCount.textContent = `${slot.currentIndex + 1}/${slot.results.length}`;
            prevBtn.disabled = false;
            nextBtn.disabled = false;
        } else {
            navControls.style.display = 'none';
        }

        if (slot.track) {
            trackSlot.classList.remove('empty');
            trackSlot.classList.add('filled');
            trackSlot.innerHTML = '';
            trackSlot.appendChild(Components.renderTrack(slot.track, { showActions: true, minimal: true }));
            // Re-add remove button for steer slots
            if (slotName.startsWith('steer-')) {
                const removeBtn = document.createElement('button');
                removeBtn.className = 'remove-steer-btn';
                removeBtn.title = 'Remove';
                removeBtn.textContent = '×';
                removeBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.removeSteerSlot(slotName);
                });
                trackSlot.appendChild(removeBtn);
            }
        } else {
            trackSlot.classList.add('empty');
            trackSlot.classList.remove('filled');
            let html = `<span class="placeholder">Drag track here or type above</span>`;
            if (slotName.startsWith('steer-')) {
                html += `<button class="remove-steer-btn" title="Remove">×</button>`;
            }
            trackSlot.innerHTML = html;
            // Re-bind remove button
            const removeBtn = trackSlot.querySelector('.remove-steer-btn');
            if (removeBtn) {
                removeBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.removeSteerSlot(slotName);
                });
            }
        }
    },

    renderPlaylist() {
        const container = document.getElementById('playlist');
        Components.renderTrackList(container, this.generatedPlaylist, { inPlaylist: true });
    }
};

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => App.init());
