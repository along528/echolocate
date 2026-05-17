/**
 * UI Components for rendering tracks
 */

// Lucide-style icons used in the track action row. 16x16, currentColor,
// drop-in <svg> markup so we can embed them directly in template strings.
const TRACK_ICONS = {
    listPlus:   '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11 12H3"/><path d="M16 6H3"/><path d="M16 18H3"/><path d="M18 9v6"/><path d="M21 12h-6"/></svg>',
    similar:    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12h2"/><path d="M6 8v8"/><path d="M10 5v14"/><path d="M14 8v8"/><path d="M18 11v2"/><path d="M22 12h-2"/></svg>',
    dissimilar: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 12h2"/><path d="M7 9v6"/><path d="M11 6v12"/><path d="M15 9v6"/><path d="M19 11v2"/><path d="M4 20 20 4"/></svg>',
    check:      '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="20 6 9 17 4 12"/></svg>',
    tilde:      '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 13c1-2 2.5-3 4-3s2.5 1.5 4.5 3 3 3 4.5 3 3-1 5-3"/></svg>',
    x:          '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>',
    close:      '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.25" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>',
};

const Components = {

    renderTrack(track, options = {}) {
        const { showActions = true, inPlaylist = false, minimal = false } = options;

        const div = document.createElement('div');
        div.className = 'track-item';
        div.dataset.trackId = track.id;

        // Draggable
        div.draggable = true;
        div.addEventListener('dragstart', (e) => {
            e.dataTransfer.setData('text/plain', JSON.stringify(track));
            e.dataTransfer.effectAllowed = 'copy';

            // Custom drag image (smaller)
            const ghost = document.createElement('div');
            ghost.className = 'track-drag-ghost';
            ghost.textContent = `${track.artist} - ${track.title}`;
            document.body.appendChild(ghost);

            // We need to ensure it's rendered, so we use it immediately
            // Setting position to be off-screen can sometimes cause issues with setDragImage on some browsers if not painted
            // But let's try standard approach. To be safe, we can place it at 0,0 but z-index high, then remove.
            ghost.style.top = '0';
            ghost.style.left = '0';

            e.dataTransfer.setDragImage(ghost, 0, 0);

            // Remove after a short delay to allow the browser to capture the image
            setTimeout(() => document.body.removeChild(ghost), 0);
        });

        const isPlaying = Player.currentTrack?.id === track.id;
        if (isPlaying) {
            div.classList.add('playing');
        }

        // Highlight special tracks in the generated playlist
        if (inPlaylist) {
            if (track.isStart) div.classList.add('track-card', 'is-start');
            if (track.isSteering) div.classList.add('track-card', 'is-steering');
            if (track.isEnd) div.classList.add('track-card', 'is-end');
        }

        const labelable = !!track._searchId && showActions && !minimal;
        const titleHtml = track.track_url
            ? `<a href="${this.escapeHtml(track.track_url)}" target="_blank" rel="noopener noreferrer" class="track-title-link" title="Open source (long-press on mobile)">${this.escapeHtml(track.title)}<span class="track-title-link-icon" aria-hidden="true">↗</span></a>`
            : this.escapeHtml(track.title);
        div.innerHTML = `
            <div class="track-info">
                <div class="track-title">${titleHtml}</div>
                <div class="track-artist">${this.escapeHtml(track.artist)} — ${this.escapeHtml(track.album)}</div>
            </div>
            ${showActions ? `
            <div class="track-actions">
                ${!inPlaylist && !minimal ? `
                    <div class="actions-cluster" role="group" aria-label="Queue actions">
                        <button class="action-btn cluster-btn primary add-action" title="Add to playlist">${TRACK_ICONS.listPlus}</button>
                        ${!options.hideSimilar ? `
                            <button class="action-btn cluster-btn similar-action" title="Find similar">${TRACK_ICONS.similar}</button>
                            <button class="action-btn cluster-btn dissimilar-action" title="Find dissimilar">${TRACK_ICONS.dissimilar}</button>
                        ` : ''}
                    </div>
                ` : ''}
                ${labelable ? `
                    <div class="match-pill label-group" role="group" aria-label="Rate match">
                        <span class="mp-label">Match</span>
                        <button class="action-btn mp-btn mp-yes label-action label-relevant"   data-signal="relevant"   title="Relevant">${TRACK_ICONS.check}</button>
                        <button class="action-btn mp-btn mp-mid label-action label-borderline" data-signal="borderline" title="Borderline (add a note)">${TRACK_ICONS.tilde}</button>
                        <button class="action-btn mp-btn mp-no  label-action label-wrong"      data-signal="wrong"      title="Wrong (add a note)">${TRACK_ICONS.x}</button>
                    </div>
                ` : ''}
                ${inPlaylist && !minimal ? `
                    <button class="action-btn remove-action" title="Remove">${TRACK_ICONS.close}</button>
                ` : ''}
            </div>
            ` : ''}
        `;

        // Title link: opens external URL.
        // - Mouse/pen: a normal click navigates.
        // - Touch: requires a long-press (~350ms). A short tap on the title
        //   falls through to the row click handler (i.e. plays the track),
        //   protecting against accidental fat-finger navigations on mobile.
        const titleLink = div.querySelector('.track-title-link');
        if (titleLink) {
            let pointerType = 'mouse';
            let longPressed = false;
            let pressTimer = null;
            const LONG_PRESS_MS = 350;
            const cancel = () => {
                if (pressTimer) { clearTimeout(pressTimer); pressTimer = null; }
            };
            titleLink.addEventListener('pointerdown', (e) => {
                pointerType = e.pointerType;
                longPressed = false;
                if (e.pointerType === 'touch') {
                    cancel();
                    pressTimer = setTimeout(() => {
                        longPressed = true;
                        window.open(titleLink.href, '_blank', 'noopener,noreferrer');
                    }, LONG_PRESS_MS);
                }
            });
            ['pointerup', 'pointercancel', 'pointerleave', 'pointermove'].forEach(ev => {
                titleLink.addEventListener(ev, cancel);
            });
            titleLink.addEventListener('click', (e) => {
                if (pointerType === 'touch') {
                    e.preventDefault();
                    if (longPressed) {
                        e.stopPropagation();
                        longPressed = false;
                    }
                } else {
                    e.stopPropagation();
                }
            });
        }

        // Add to builder (Smart Add)
        div.querySelector('.add-action')?.addEventListener('click', (e) => {
            e.stopPropagation();
            if (typeof App.addTrackToBuilder === 'function') {
                App.addTrackToBuilder(track);
            } else {
                // Fallback if App isn't ready or changed
                console.warn('App.addTrackToBuilder is not defined');
            }
        });

        // Find similar
        div.querySelector('.similar-action')?.addEventListener('click', (e) => {
            e.stopPropagation();
            App.findSimilar(track);
        });

        // Find dissimilar
        div.querySelector('.dissimilar-action')?.addEventListener('click', (e) => {
            e.stopPropagation();
            App.findDissimilar(track);
        });

        // Remove from playlist
        div.querySelector('.remove-action')?.addEventListener('click', (e) => {
            e.stopPropagation();
            const index = Player.playlist.findIndex(t => t.id === track.id);
            if (index !== -1) {
                Player.playlist.splice(index, 1);
                App.renderPlaylist();
            }
        });

        // 3-way label buttons (only present when track has _searchId).
        // Borderline / Wrong open an inline note row beneath the actions
        // (no browser modal). The label is recorded immediately on click so
        // navigating away still captures the rating; the note is appended
        // when the user presses Save or Enter.
        div.querySelectorAll('.label-action').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const signal = btn.dataset.signal;
                const group = btn.parentElement;
                const wasSelected = btn.classList.contains('selected');
                group.querySelectorAll('.label-action').forEach(b => b.classList.remove('selected'));

                // Always remove any open note row before re-evaluating
                this._closeNoteRow(div);

                if (wasSelected) {
                    Labels.recordLabel(track, 'cleared', null);
                    return;
                }
                btn.classList.add('selected');

                // Record immediately with no note. If the user types one in the
                // inline row and saves, we'll call recordLabel again to attach it.
                Labels.recordLabel(track, signal, null);

                if (signal === 'borderline' || signal === 'wrong') {
                    this._openNoteRow(div, track, signal);
                }
            });
        });

        // Click row to play
        div.addEventListener('click', () => Player.play(track, options.context));

        return div;
    },

    renderTrackList(container, tracks, options = {}) {
        const { clear = true } = options;
        if (clear) {
            container.innerHTML = '';
        }
        tracks.forEach(track => {
            // Pass the current list as context to renderTrack
            container.appendChild(this.renderTrack(track, { ...options, context: tracks }));
        });
    },

    // ─── Inline note row (replaces window.prompt for Borderline / Wrong) ───
    _closeNoteRow(trackDiv) {
        const existing = trackDiv.querySelector('.note-row');
        if (existing) existing.remove();
        trackDiv.classList.remove('has-note');
    },

    _openNoteRow(trackDiv, track, signal) {
        // signal is 'borderline' or 'wrong' — map to the same color classes
        // the match-pill uses ('mid' / 'no') so the styling stays consistent.
        const tone = signal === 'borderline' ? 'mid' : 'no';
        const prompt = signal === 'borderline' ? 'Why borderline?' : "What's off?";
        const placeholder = signal === 'borderline'
            ? 'e.g. "right vibe, wrong era"'
            : 'e.g. "too rock"';

        const row = document.createElement('div');
        row.className = `note-row ${tone}`;
        row.innerHTML = `
            <span class="note-prompt">${prompt}<span class="note-optional"> · optional</span></span>
            <input type="text" class="note-input ${tone}" placeholder="${placeholder}" />
            <button type="button" class="note-save ${tone}">Save</button>
        `;

        // Stop clicks inside the note row from bubbling up and triggering
        // Player.play() (the row click handler on .track-item).
        row.addEventListener('click', (e) => e.stopPropagation());

        const input = row.querySelector('.note-input');
        const save  = row.querySelector('.note-save');

        // Always commit whatever's in the input (empty = no note). The label
        // itself was already recorded on the rate-button click; this only
        // attaches the optional note.
        let committed = false;
        const commit = () => {
            if (committed) return;
            committed = true;
            const text = (input.value || '').trim();
            if (text) Labels.recordLabel(track, signal, text);
            this._closeNoteRow(trackDiv);
        };

        save.addEventListener('click', commit);
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === 'Escape') {
                e.preventDefault();
                commit();
            }
        });
        // Clicking elsewhere on the page commits + closes.
        input.addEventListener('blur', () => {
            // Defer slightly so a click on Save fires before blur tears down.
            setTimeout(commit, 0);
        });

        trackDiv.classList.add('has-note');
        trackDiv.appendChild(row);
        // Focus shortly after append so iOS doesn't suppress the keyboard.
        setTimeout(() => input.focus(), 0);
    },

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text || '';
        return div.innerHTML;
    }
};
