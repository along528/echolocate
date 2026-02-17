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
        start: { id: 'start', track: null, query: '', results: [], currentIndex: -1, enhancedQuery: null, isEditing: false },
        end: { id: 'end', track: null, query: '', results: [], currentIndex: -1, enhancedQuery: null, isEditing: false }
    },
    steerSlots: [],
    steerCounter: 0,


    init() {
        Player.init();
        const restored = this.restoreState();
        this.setupEventListeners();
        this.setupMobileNavigation();
        this.setupDragAndDrop();
        if (restored) {
            // Sync DOM inputs to restored state
            const searchInput = document.getElementById('search-input');
            if (searchInput && this._savedSearchValue) {
                searchInput.value = this._savedSearchValue;
            }
            delete this._savedSearchValue;

            // Sync search mode tabs
            document.querySelectorAll('.tab').forEach(t => {
                t.classList.toggle('active', t.dataset.tab === this.searchMode);
            });

            // Sync enhance toggle
            const toggle = document.getElementById('enhance-toggle');
            if (toggle) toggle.checked = this.enhanceQuery;

            // Rebuild steer slot DOM elements from restored state
            const container = document.getElementById('steer-slots-container');
            this.steerSlots.forEach(slot => {
                const el = this.createSteerSlotElement(slot.id);
                container.appendChild(el);
                if (!slot.isInterpolated) {
                    this.setupSlotListeners(slot.id);
                }
                this.setupSlotDragDrop(slot.id);
            });

            this.renderResults();
            this.renderBuilder();
        } else {
            this.loadInitialTracks();
            this.renderBuilder();
        }
        this.updateUIState();
    },

    saveState() {
        try {
            const serializeSlot = (slot) => ({
                id: slot.id,
                track: slot.track,
                query: slot.query,
                results: slot.results,
                currentIndex: slot.currentIndex,
                enhancedQuery: slot.enhancedQuery,
                isEditing: slot.isEditing,
                dismissed: slot.dismissed,
                isInterpolated: slot.isInterpolated
            });

            const builderState = {
                start: serializeSlot(this.slots.start),
                end: serializeSlot(this.slots.end),
                steerSlots: this.steerSlots.map(serializeSlot),
                steerCounter: this.steerCounter
            };
            localStorage.setItem('echolocate-builder', JSON.stringify(builderState));

            const searchState = {
                searchMode: this.searchMode,
                enhanceQuery: this.enhanceQuery,
                results: this.results,
                pinnedTrack: this.pinnedTrack,
                searchValue: document.getElementById('search-input')?.value || ''
            };
            localStorage.setItem('echolocate-search', JSON.stringify(searchState));
        } catch (e) {
            console.warn('Failed to save app state:', e);
        }
    },

    restoreState() {
        try {
            const builderRaw = localStorage.getItem('echolocate-builder');
            const searchRaw = localStorage.getItem('echolocate-search');
            if (!builderRaw && !searchRaw) return false;

            if (builderRaw) {
                const builder = JSON.parse(builderRaw);
                // Restore fixed slots
                if (builder.start) Object.assign(this.slots.start, builder.start);
                if (builder.end) Object.assign(this.slots.end, builder.end);
                if (builder.steerSlots) this.steerSlots = builder.steerSlots;
                if (builder.steerCounter != null) this.steerCounter = builder.steerCounter;
            }

            if (searchRaw) {
                const search = JSON.parse(searchRaw);
                if (search.searchMode) this.searchMode = search.searchMode;
                if (search.enhanceQuery != null) this.enhanceQuery = search.enhanceQuery;
                if (search.results) this.results = search.results;
                if (search.pinnedTrack !== undefined) this.pinnedTrack = search.pinnedTrack;
                // Stash search input value for init() to apply after DOM is ready
                this._savedSearchValue = search.searchValue || '';
            }

            return true;
        } catch (e) {
            console.warn('Failed to restore app state:', e);
            return false;
        }
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
                this.saveState();
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
                this.saveState();
            });
        }

        // Builder controls
        document.getElementById('clear-builder').addEventListener('click', () => {
            this.resetSlots();
            this.renderBuilder();
            document.getElementById('builder-view').style.display = 'block';
        });





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
        const randomizeBtn = container.querySelector('.slot-randomize-btn');
        const searchBtn = container.querySelector('.slot-search-btn');

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

        if (searchBtn) {
            searchBtn.addEventListener('click', () => {
                const slot = this.getSlot(slotName);
                if (slot && slot.query) this.handleSlotSearch(slotName, slot.query);
            });
        }

        if (randomizeBtn) {
            randomizeBtn.addEventListener('click', () => this.handleSlotRandomize(slotName));
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

    setupMobileNavigation() {
        // Mobile Navigation Logic
        const mobileTabs = document.querySelectorAll('.mobile-tab');
        const resultsPanel = document.querySelector('.results-panel');
        const playlistPanel = document.querySelector('.playlist-panel');

        // Function to set active mobile view
        const setMobileView = (viewName) => {
            // Update tabs
            mobileTabs.forEach(tab => {
                if (tab.dataset.mobileTab === viewName) {
                    tab.classList.add('active');
                } else {
                    tab.classList.remove('active');
                }
            });

            // Update panels
            if (viewName === 'search') {
                if (resultsPanel) resultsPanel.classList.add('active');
                if (playlistPanel) playlistPanel.classList.remove('active');
            } else if (viewName === 'playlist') {
                if (playlistPanel) playlistPanel.classList.add('active');
                if (resultsPanel) resultsPanel.classList.remove('active');
            }
        };

        // Event Listeners
        mobileTabs.forEach(tab => {
            tab.addEventListener('click', () => {
                setMobileView(tab.dataset.mobileTab);
            });
        });

        // Initialize Mobile View (Default to Search on mobile load)
        const isMobile = window.innerWidth <= 900;
        if (isMobile) {
            setMobileView('search');
        } else {
            // Reset for desktop
            if (resultsPanel) resultsPanel.classList.add('active');
            if (playlistPanel) playlistPanel.classList.add('active');
        }

        // Handle Resize
        window.addEventListener('resize', () => {
            if (window.innerWidth > 900) {
                // Ensure both are visible on desktop
                if (resultsPanel) resultsPanel.classList.add('active');
                if (playlistPanel) playlistPanel.classList.add('active');
            } else {
                // Revert to last known or default on mobile
                // Default to playlist if unclear which one should be active
                if (resultsPanel && playlistPanel &&
                    resultsPanel.classList.contains('active') &&
                    playlistPanel.classList.contains('active')) {
                    setMobileView('playlist');
                }
            }
        });
    },

    addSteerSlot(track = null, insertIndex = -1, options = {}) {
        const { isInterpolated = false, skipRender = false, animate = false } = options;
        const slotId = `steer-${this.steerCounter++}`;
        const slotState = {
            id: slotId,
            track: track || null,
            query: '',
            results: [],
            currentIndex: -1,
            enhancedQuery: null,
            isInterpolated,
            isEditing: !track, // If no track, start in edit mode
            animate // Store animate flag to be used in creation
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

        // Bind listeners (search input) only for non-interpolated slots
        if (!isInterpolated) {
            this.setupSlotListeners(slotId);
        }
        this.setupSlotDragDrop(slotId);

        if (track) {
            this.removeTrackFromResults(track.id);
        }

        if (!skipRender) this.renderBuilder();
        return slotId;
    },

    createSteerSlotElement(slotId) {
        const slot = this.getSlot(slotId);
        const div = document.createElement('div');
        div.className = 'slot-container steer-slot-container';
        if (slot?.isInterpolated) div.classList.add('interpolated-slot');
        if (slot?.animate) {
            div.classList.add('entering');
            // Disable flag after use so it doesn't re-animate on re-render? 
            // Actually re-renders might replace the element. 
            // But usually we just update contents.
            // If we replace the element, we might want to not animate again.
            slot.animate = false;
        }
        div.dataset.slot = slotId;

        div.innerHTML = `
            <div class="slot-header" style="display: flex; justify-content: flex-end; align-items: center; margin-bottom: 0.5rem; height: 16px;">
                <div class="slot-controls" style="display: flex; gap: 4px;">
                    <!-- Controls injected by renderSlot -->
                </div>
            </div>
            ${slot?.isInterpolated ? '' : `
            <div class="slot-mode-edit" style="display: none;">
                <div class="slot-input-wrapper">
                    <input type="text" class="slot-search-input" placeholder="Describe a vibe..."
                        autocomplete="off">
                    <button class="slot-search-btn" title="Search">🔍</button>
                    <button class="slot-randomize-btn" title="Pick a random track">🎲</button>
                </div>
            </div>
            `}
            <div class="slot-mode-view" style="${slot?.isInterpolated ? '' : 'display: none;'}">
                <div class="track-slot filled">
                    <!-- Configured in renderSlot -->
                </div>
            </div>
        `;

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
        slot.isEditing = true;
        slot.dismissed = false;
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
        // Target the container itself to ensure drop works in both edit and view modes
        const el = document.querySelector(`.slot-container[data-slot="${slotName}"]`);
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
        slot.isEditing = false; // Switch to view mode
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
        const searchBtn = container.querySelector('.slot-search-btn');
        input.disabled = true;
        input.classList.add('loading');
        if (searchBtn) {
            searchBtn.disabled = true;
            searchBtn.classList.add('loading');
        }

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
                slot.isEditing = false; // Switch to view mode on successful search
            } else {
                slot.results = [];
                slot.track = null;
                // Stay in edit mode if no results
            }
        } catch (e) {
            console.error(`Search for slot ${slotName} failed:`, e);
        } finally {
            if (input) {
                input.disabled = false;
                input.classList.remove('loading');
            }
            if (searchBtn) {
                searchBtn.disabled = false;
                searchBtn.classList.remove('loading');
            }
            this.renderBuilder();
        }
    },

    async handleSlotRandomize(slotName) {
        const slot = this.getSlot(slotName);
        if (!slot) return;

        const container = document.querySelector(`.slot-container[data-slot="${slotName}"]`);
        const randomizeBtn = container?.querySelector('.slot-randomize-btn');
        if (randomizeBtn) {
            randomizeBtn.disabled = true;
            randomizeBtn.classList.add('loading');
        }

        try {
            const source = this.getSelectedSource();
            const tracks = await API.getTracks(1, source);
            if (tracks.length > 0) {
                this.setSlotTrack(slotName, tracks[0]);
            }
        } catch (e) {
            console.error(`Randomize for slot ${slotName} failed:`, e);
        } finally {
            if (randomizeBtn) {
                randomizeBtn.disabled = false;
                randomizeBtn.classList.remove('loading');
            }
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

        // Scroll the navigated slot into view within the builder container
        const slotEl = document.querySelector(`.slot-container[data-slot="${slotName}"]`);
        const scrollContainer = slotEl?.closest('.builder-slots');
        if (slotEl && scrollContainer) {
            const elRect = slotEl.getBoundingClientRect();
            const containerRect = scrollContainer.getBoundingClientRect();
            const targetScroll = scrollContainer.scrollTop + (elRect.top - containerRect.top) - (scrollContainer.clientHeight / 2) + (slotEl.clientHeight / 2);
            scrollContainer.scrollTo({ top: targetScroll, behavior: 'smooth' });
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
        this.saveState();
    },

    renderBuilder() {
        // Render fixed slots (start, end)
        ['start', 'end'].forEach(slotName => this.renderSlot(slotName));
        // Render dynamic steer slots
        this.steerSlots.forEach(s => this.renderSlot(s.id));

        // Show end slot only if start track is set and not dismissed
        const endSlot = document.querySelector('.slot-container[data-slot="end"]');
        const hasStart = !!this.slots.start.track;
        const endHasContent = !!this.slots.end.track || this.slots.end.query;
        if (endSlot) endSlot.style.display = (hasStart && !this.slots.end.dismissed) || endHasContent ? '' : 'none';

        // Render "+" insert buttons between every pair of adjacent slots
        this.renderInsertButtons();



        // Sync Player Context if we are currently playing a track from the builder
        if (Player.currentTrack) {
            const builderTracks = this.getBuilderTrackList();

            console.log('Sync Check:', {
                currentId: Player.currentTrack.id,
                builderCount: builderTracks.length,
                builderIds: builderTracks.map(t => t.id)
            });

            // Only sync if the currently playing track is in the builder list
            const isPlayingFromBuilder = builderTracks.some(t => String(t.id) === String(Player.currentTrack.id));
            console.log('Is Playing From Builder?', isPlayingFromBuilder);

            if (isPlayingFromBuilder) {
                Player.updatePlaylist(builderTracks);
            }
        }
        this.saveState();
    },

    renderInsertButtons() {
        // Remove existing button groups
        document.querySelectorAll('.insert-btn-group').forEach(el => el.remove());

        const container = document.getElementById('steer-slots-container');

        const getAdjacentTracks = (index) => {
            const above = index === 0
                ? this.slots.start.track
                : this.steerSlots[index - 1]?.track;
            const below = index >= this.steerSlots.length
                ? this.slots.end.track
                : this.steerSlots[index]?.track;
            return { above, below };
        };

        const createButtonGroup = (index) => {
            const group = document.createElement('div');
            group.className = 'insert-btn-group';

            const plusBtn = document.createElement('button');
            plusBtn.className = 'insert-steer-btn';
            plusBtn.textContent = '+';
            plusBtn.title = 'Add track';
            plusBtn.addEventListener('click', () => this.addSteerSlot(null, index, { animate: true }));

            const interpBtn = document.createElement('button');
            interpBtn.className = 'insert-steer-btn insert-interp-btn';
            // Sparkle Icon (SVG)
            interpBtn.innerHTML = `
                <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                    <path d="M12 2L14.39 9.61L22 12L14.39 14.39L12 22L9.61 14.39L2 12L9.61 9.61L12 2Z"/>
                </svg>
            `;
            interpBtn.title = 'Fill between adjacent tracks';

            const { above, below } = getAdjacentTracks(index);
            if (above && below) {
                interpBtn.addEventListener('click', (e) => this.interpolateBetween(index, e.currentTarget));
            } else {
                interpBtn.disabled = true;
            }

            group.appendChild(plusBtn);
            group.appendChild(interpBtn);
            return group;
        };

        const slotElements = container.querySelectorAll('.slot-container');
        if (slotElements.length === 0) {
            container.appendChild(createButtonGroup(0));
        } else {
            slotElements.forEach((el, i) => {
                el.before(createButtonGroup(i));
            });
            slotElements[slotElements.length - 1].after(createButtonGroup(slotElements.length));
        }
    },

    async interpolateBetween(insertIndex, btnElement) {
        const above = insertIndex === 0
            ? this.slots.start.track
            : this.steerSlots[insertIndex - 1]?.track;
        const below = insertIndex >= this.steerSlots.length
            ? this.slots.end.track
            : this.steerSlots[insertIndex]?.track;

        if (!above || !below) return;

        // Set Loading State
        if (btnElement) {
            btnElement.classList.add('loading');
            btnElement.disabled = true;
        }

        try {
            const source = this.getSelectedSource();
            const tracks = await API.interpolatePlaylist(
                above.id, below.id, 5, 'greedy_walk', source
            );

            // Strip first and last (they match the adjacent tracks)
            const middleTracks = tracks.slice(1, -1);

            // Insert as interpolated steer slots in order
            for (let i = 0; i < middleTracks.length; i++) {
                this.addSteerSlot(middleTracks[i], insertIndex + i, {
                    isInterpolated: true,
                    skipRender: true,
                    animate: true
                });
            }
            this.renderBuilder();
        } catch (error) {
            console.error('Interpolation between tracks failed:', error);
            // Revert loading on error (if succeed, button is removed by render)
            if (btnElement) {
                btnElement.classList.remove('loading');
                btnElement.disabled = false;
            }
        }
    },

    getBuilderTrackList() {
        const tracks = [];
        if (this.slots.start.track) tracks.push(this.slots.start.track);
        this.steerSlots.forEach(s => {
            if (s.track) tracks.push(s.track);
        });
        if (this.slots.end.track) tracks.push(this.slots.end.track);
        return tracks;
    },

    renderSlot(slotName) {
        const slot = this.getSlot(slotName);
        const container = document.querySelector(`.slot-container[data-slot="${slotName}"]`);
        if (!container || !slot) return;

        // Get current sequence of tracks in builder for player context
        const builderContext = this.getBuilderTrackList();
        // console.log('Builder context for', slotName, builderContext.length, 'tracks');

        // --- Render Interpolated Slot ---
        if (slot.isInterpolated) {
            const trackSlot = container.querySelector('.track-slot');
            if (!trackSlot) return; // Should be there

            if (slot.track) {
                trackSlot.classList.remove('empty');
                trackSlot.classList.add('filled');
                trackSlot.innerHTML = '';

                // Render track card with context
                const card = Components.renderTrack(slot.track, {
                    showActions: true,
                    minimal: true,
                    context: builderContext
                });
                // Inline controls for interpolated slot (mobile: × button)
                const inlineControls = document.createElement('div');
                inlineControls.className = 'slot-controls-inline';
                const removeBtn = document.createElement('button');
                removeBtn.className = 'action-btn slot-inline-btn remove-inline-btn';
                removeBtn.innerHTML = '×';
                removeBtn.title = 'Remove';
                removeBtn.onclick = (e) => { e.stopPropagation(); this.removeSteerSlot(slotName); };
                inlineControls.appendChild(removeBtn);
                card.appendChild(inlineControls);

                trackSlot.appendChild(card);
            } else {
                // Should not really happen for interpolated, but fallback
                trackSlot.classList.add('empty');
                trackSlot.classList.remove('filled');
                trackSlot.innerHTML = `<span class="placeholder">Interpolated</span>`;
            }

            // Ensure header controls are structured like manual slots for consistent "x" button
            // Interpolated slots don't usually have a header, but we want the "x" to be consistent.
            // Actually, manual slots have the "x" in the header (slot-controls).
            // Interpolated slots currently don't have a header in createSteerSlotElement.
            // Let's modify createSteerSlotElement to include a header for interpolated slots too, 
            // OR just add the "x" button in a similar style.

            // The user wants "same style and position for the x". 
            // Manual slots have `slot-header` with `slot-controls` containing the `x`.

            // Let's add an absolute positioned X that mimics the header X, OR
            // better yet, let's just make interpolated slots have a header like manual slots, 
            // but without the label/search parts. 
            // But createSteerSlotElement is already baked. 

            // Let's just use the existing removeBtn but style it to match `.header-nav-btn`.
            // AND position it similarly (top right).

            // Actually, the previous implementation added a `remove-steer-btn` overlaid.
            // The user wants it to look like the non-interpolated ones. 
            // Non-interpolated: `.header-nav-btn` in `.slot-controls` (header).

            // Simplest Fix: Add a "slot-header" structure to interpolated slots dynamically if missing,
            // or just absolute position a button that looks exactly like the header one.

            // Let's try adding a small header container inside the slot if we can, 
            // or just overlapping. 

            // Current manual slot structure:
            // .slot-container
            //   .slot-header
            //     .slot-controls -> .header-nav-btn ("x")

            // Current interpolated structure:
            // .slot-container.interpolated-slot
            //   .track-slot.filled

            // If we want EXACT style/position, we should probably add the header.
            // But `createSteerSlotElement` makes the structure.
            // We can adjust `createSteerSlotElement` to be uniform?
            // Or just prepend a header here.
        }

        // --- Render Standard Slot (Start, End, Manual Steer) ---
        // Areas
        const editModeDiv = container.querySelector('.slot-mode-edit');
        const viewModeDiv = container.querySelector('.slot-mode-view');
        const emptyModeDiv = container.querySelector('.track-slot.empty');

        // For standard start/end slots, ensure DOM structure exists (and has new controls)
        const hasControls = container.querySelector('.slot-controls');
        if ((!editModeDiv || !hasControls) && (slotName === 'start' || slotName === 'end')) {
            container.innerHTML = `
                <div class="slot-header" style="display: flex; justify-content: flex-end; align-items: center; margin-bottom: 0.5rem; height: 16px;">
                    <label style="margin-bottom: 0; margin-right: auto;">${slotName === 'start' ? 'Start Track' : 'End Track'}</label>
                    <div class="slot-controls" style="display: flex; gap: 4px;"></div>
                </div>
                <div class="slot-mode-edit" style="display: none;">
                    <div class="slot-input-wrapper">
                        <input type="text" class="slot-search-input" placeholder="Describe a vibe..." autocomplete="off">
                        <button class="slot-search-btn" title="Search">🔍</button>
                        <button class="slot-randomize-btn" title="Pick a random track">🎲</button>
                    </div>
                </div>
                <div class="slot-mode-view" style="display: none;">
                    <div class="track-slot filled"></div>
                </div>
            `;
            // Re-bind listeners for new elements
            this.setupSlotListeners(slotName);
            this.setupSlotDragDrop(slotName);
            return this.renderSlot(slotName); // Retry
        }

        const input = container.querySelector('.slot-search-input');
        const slotControls = container.querySelector('.slot-controls');

        // --- Populate Header Controls: Left, Right, Edit, X ---
        if (slotControls) {
            slotControls.innerHTML = ''; // Clear existing

            // Helper to create header btn
            const createBtn = (icon, title, onClick, extraClass = '') => {
                const btn = document.createElement('button');
                btn.className = `header-nav-btn ${extraClass}`; // Reuse style
                btn.innerHTML = icon;
                btn.title = title;
                btn.onclick = (e) => { e.stopPropagation(); onClick(e); };
                return btn;
            };

            // 1. Left/Right Nav (only if multiple results AND viewed/filled)
            if (slot.results && slot.results.length > 1 && !slot.isEditing && slot.track) {
                slotControls.appendChild(createBtn('←', 'Previous result', () => this.navigateSlot(slotName, -1), 'prev'));
                slotControls.appendChild(createBtn('→', 'Next result', () => this.navigateSlot(slotName, 1), 'next'));
            }

            // 2. Edit Button (only if viewed/filled AND NOT INTERPOLATED)
            if (!slot.isEditing && slot.track && !slot.isInterpolated) {
                slotControls.appendChild(createBtn('✎', 'Edit', () => {
                    slot.isEditing = true;
                    this.renderSlot(slotName);
                }, 'edit-control-btn'));
            }

            // 3. Remove Button (only for steer slots)
            if (slotName.startsWith('steer-')) {
                slotControls.appendChild(createBtn('×', 'Remove Slot', () => this.removeSteerSlot(slotName), 'remove-control-btn'));
            }

            // 4. Clear Button (for start/end slots when they have a track)
            if ((slotName === 'start' || slotName === 'end') && slot.track) {
                slotControls.appendChild(createBtn('×', 'Clear', () => {
                    this.resetSlot(slotName);
                    this.renderBuilder();
                }, 'remove-control-btn'));
            }
        }

        // --- Logic to determine state ---
        if (!slot.track && !slot.isEditing) {
            // No track selected — show edit mode so user can search or randomize
            if (editModeDiv) editModeDiv.style.display = 'block';
            if (viewModeDiv) viewModeDiv.style.display = 'none';
        } else if (slot.isEditing) {
            // Show Edit Input
            if (editModeDiv) editModeDiv.style.display = 'block';
            if (viewModeDiv) viewModeDiv.style.display = 'none';
            if (emptyModeDiv) emptyModeDiv.style.display = 'none';

            if (input) {
                input.value = slot.query;
                input.focus();
            }
        } else {
            // Show View (Track Card)
            if (editModeDiv) editModeDiv.style.display = 'none';
            if (viewModeDiv) viewModeDiv.style.display = 'block';
            if (emptyModeDiv) emptyModeDiv.style.display = 'none';

            const filledSlot = viewModeDiv.querySelector('.track-slot.filled');
            filledSlot.innerHTML = '';

            // Render Track
            const card = Components.renderTrack(slot.track, {
                showActions: true,
                minimal: true,
                context: builderContext
            });

            // --- Inline Slot Controls (for mobile: same row as play/url buttons) ---
            const inlineControls = document.createElement('div');
            inlineControls.className = 'slot-controls-inline';

            const createInlineBtn = (icon, title, onClick, extraClass = '') => {
                const btn = document.createElement('button');
                btn.className = `action-btn slot-inline-btn ${extraClass}`;
                btn.innerHTML = icon;
                btn.title = title;
                btn.onclick = (e) => { e.stopPropagation(); onClick(e); };
                return btn;
            };

            if (slot.results && slot.results.length > 1) {
                inlineControls.appendChild(createInlineBtn('←', 'Previous result', () => this.navigateSlot(slotName, -1)));
                inlineControls.appendChild(createInlineBtn('→', 'Next result', () => this.navigateSlot(slotName, 1)));
            }
            if (!slot.isInterpolated) {
                inlineControls.appendChild(createInlineBtn('✎', 'Edit', () => {
                    slot.isEditing = true;
                    this.renderSlot(slotName);
                }));
            }
            if (slotName.startsWith('steer-')) {
                inlineControls.appendChild(createInlineBtn('×', 'Remove', () => this.removeSteerSlot(slotName), 'remove-inline-btn'));
            } else if (slot.track) {
                inlineControls.appendChild(createInlineBtn('×', 'Clear', () => {
                    this.resetSlot(slotName);
                    this.renderBuilder();
                }, 'remove-inline-btn'));
            }

            card.appendChild(inlineControls);

            // --- Footer: Enhanced Text Only (Nav/Edit moved to header) ---
            if (slot.enhancedQuery) {
                const footer = document.createElement('div');
                footer.className = 'track-card-footer';

                const footerTools = document.createElement('div');
                footerTools.className = 'footer-tools';
                footerTools.style.display = 'flex';
                footerTools.style.alignItems = 'center';

                // Enhanced Text
                const text = document.createElement('div');
                text.className = 'footer-enhanced-text';
                text.innerHTML = `✨ ${slot.enhancedQuery}`;
                text.title = slot.enhancedQuery;
                text.style.marginLeft = '0';
                footerTools.appendChild(text);

                footer.appendChild(footerTools);
                card.appendChild(footer);
            }

            filledSlot.appendChild(card);
        }

        // --- Mobile edit-mode action buttons (cancel / remove) ---
        // Runs for both edit-mode branches (no track, or editing existing)
        const inputWrapper = editModeDiv?.querySelector('.slot-input-wrapper');
        if (inputWrapper && editModeDiv?.style.display !== 'none') {
            // Remove any previously rendered edit-mode actions
            inputWrapper.querySelector('.edit-mode-actions')?.remove();

            const actions = document.createElement('div');
            actions.className = 'edit-mode-actions';

            if (slot.track) {
                // Cancel button: editing a slot that already has a track
                const cancelBtn = document.createElement('button');
                cancelBtn.className = 'edit-mode-action-btn cancel-edit-btn';
                cancelBtn.innerHTML = '↩';
                cancelBtn.title = 'Cancel editing';
                cancelBtn.onclick = (e) => {
                    e.stopPropagation();
                    slot.isEditing = false;
                    this.renderSlot(slotName);
                };
                actions.appendChild(cancelBtn);
            } else if (slotName.startsWith('steer-') || slotName === 'end') {
                // Remove/clear button: empty search box,
                // unless it's the only search box visible.
                // End slot can always be cleared since start is always present.
                const canRemove = slotName === 'end' || [
                    this.slots.start,
                    this.slots.end,
                    ...this.steerSlots
                ].filter(s => s && s.id !== slot.id && (s.isEditing || !s.track)).length > 0;
                if (canRemove) {
                    const removeBtn = document.createElement('button');
                    removeBtn.className = 'edit-mode-action-btn remove-edit-btn';
                    removeBtn.innerHTML = '×';
                    removeBtn.title = slotName === 'end' ? 'Clear' : 'Remove slot';
                    removeBtn.onclick = (e) => {
                        e.stopPropagation();
                        if (slotName.startsWith('steer-')) {
                            this.removeSteerSlot(slotName);
                        } else if (slotName === 'end') {
                            this.resetSlot(slotName);
                            this.slots.end.dismissed = true;
                            this.renderBuilder();
                        }
                    };
                    actions.appendChild(removeBtn);
                }
            }

            if (actions.children.length > 0) {
                inputWrapper.appendChild(actions);
            }
        }
    },


};

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => App.init());
