/**
 * UI Components for rendering tracks
 */

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
        div.innerHTML = `
            <div class="track-info">
                <div class="track-title">${this.escapeHtml(track.title)}</div>
                <div class="track-artist">${this.escapeHtml(track.artist)} — ${this.escapeHtml(track.album)}</div>
            </div>
            ${showActions ? `
            <div class="track-actions">
                <button class="action-btn play-action" title="Play">▶</button>
                ${track.track_url ? `
                    <a href="${track.track_url}" target="_blank" class="action-btn link-action" title="View Source">↗</a>
                ` : ''}
                ${!inPlaylist && !minimal ? `
                    <button class="action-btn add-action" title="Add to builder">+</button>
                    ${!options.hideSimilar ? `
                        <button class="action-btn similar-action" title="Find similar">≈</button>
                        <button class="action-btn dissimilar-action" title="Find dissimilar">≠</button>
                    ` : ''}
                ` : ''}
                ${labelable ? `
                    <span class="label-group" title="How relevant is this result?">
                        <button class="action-btn label-action label-relevant" data-signal="relevant" title="Relevant">✓</button>
                        <button class="action-btn label-action label-borderline" data-signal="borderline" title="Borderline (note optional)">~</button>
                        <button class="action-btn label-action label-wrong" data-signal="wrong" title="Wrong (note optional)">✗</button>
                    </span>
                ` : ''}
                ${inPlaylist && !minimal ? `
                    <button class="action-btn remove-action" title="Remove">×</button>
                ` : ''}
            </div>
            ` : ''}
        `;

        // Play on click
        div.querySelector('.play-action')?.addEventListener('click', (e) => {
            e.stopPropagation();
            Player.play(track, options.context);
        });

        // External link click prevention (let the link work but stop row click)
        div.querySelector('.link-action')?.addEventListener('click', (e) => {
            e.stopPropagation();
        });

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

        // 3-way label buttons (only present when track has _searchId)
        div.querySelectorAll('.label-action').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const signal = btn.dataset.signal;
                const group = btn.parentElement;
                const wasSelected = btn.classList.contains('selected');
                group.querySelectorAll('.label-action').forEach(b => b.classList.remove('selected'));

                if (wasSelected) {
                    Labels.recordLabel(track, 'cleared', null);
                    return;
                }
                btn.classList.add('selected');

                let note = null;
                if (signal === 'borderline' || signal === 'wrong') {
                    const entered = window.prompt('Optional note (e.g. "too rock", "right vibe wrong era"):', '');
                    if (entered && entered.trim()) note = entered.trim();
                }
                Labels.recordLabel(track, signal, note);
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

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text || '';
        return div.innerHTML;
    }
};
