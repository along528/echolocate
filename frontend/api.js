/**
 * API Client for EchoLocate Vector Service
 */

const API = {
    // Vector service URL - configure via window.VECTOR_API_URL or defaults to same origin for local dev
    baseUrl: window.VECTOR_API_URL || '',

    async request(method, path, body = null, params = null) {
        let url = `${this.baseUrl}${path}`;

        if (params) {
            const searchParams = new URLSearchParams(params);
            url += `?${searchParams}`;
        }

        const options = {
            method,
            headers: { 'Content-Type': 'application/json' }
        };

        if (body) {
            options.body = JSON.stringify(body);
        }

        const response = await fetch(url, options);
        if (!response.ok) {
            throw new Error(`API error: ${response.status}`);
        }
        return response.json();
    },

    // Text search by artist, title, album
    async textSearch(query, source = 'fma', limit = 50) {
        return this.request('GET', '/search', null, { query, source, limit });
    },

    // Semantic search with natural language (checks Firestore cache first)
    async semanticSearch(query, source = 'fma', limit = 50, enhance = false) {
        const body = { query, source, limit, enhance };

        // Always fire the live request to keep vector-rs warm
        const liveRequest = this.request('POST', '/semantic-search', body);

        // Check cache (fast path)
        try {
            const cached = await SearchCache.get(query, source, limit, enhance);
            if (cached) {
                // Let the live request complete in the background (warm-up)
                liveRequest.catch(err => console.warn('[API] Background warm-up failed:', err));
                // Small delay so UX feels similar to a live request
                await new Promise(r => setTimeout(r, 500));
                return cached;
            }
        } catch (e) {
            console.warn('[API] Cache lookup failed, falling through to live:', e);
        }

        // Cache miss — await the live request
        return liveRequest;
    },

    // Get random tracks
    async getTracks(limit = 50, source = 'fma') {
        return this.request('GET', '/tracks', null, { limit, source, random: true });
    },

    // Find similar tracks
    async findSimilar(trackId, source = 'fma', limit = 10) {
        return this.request('GET', `/tracks/${trackId}/similar`, null, { source, limit });
    },

    // Find dissimilar tracks
    async findDissimilar(trackId, source = 'fma', limit = 10) {
        return this.request('GET', `/tracks/${trackId}/dissimilar`, null, { source, limit });
    },

    // Interpolate playlist between two tracks
    async interpolatePlaylist(trackId1, trackId2, limit = 10, method = 'greedy_walk', source = 'fma', steerTrackIds = []) {
        const body = {
            track_id_1: trackId1,
            track_id_2: trackId2,
            limit,
            method,
            source
        };
        if (steerTrackIds.length > 0) {
            body.steer_track_ids = steerTrackIds;
        }
        return this.request('POST', '/interpolate/playlist', body);
    },

    // Get stream URL for a track
    getStreamUrl(trackId) {
        return `${this.baseUrl}/stream/${trackId}`;
    },

    // Versions (index, model, git_sha) for labelling lineage
    async getVersion() {
        return this.request('GET', '/version');
    },

    // Fire-and-forget label event logging. Never throws; never blocks UX.
    logSearchEvent(payload) {
        this._fireAndForget('/labels/search', payload);
    },

    logLabelEvent(payload) {
        this._fireAndForget('/labels/result', payload);
    },

    _fireAndForget(path, payload) {
        try {
            const url = `${this.baseUrl}${path}`;
            // Plain fetch with keepalive survives navigation up to ~64KB.
            // We deliberately avoid sendBeacon: it sends credentials by default,
            // which forces a CORS preflight requiring Access-Control-Allow-Credentials.
            fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
                keepalive: true,
                credentials: 'omit',
                mode: 'cors'
            }).catch(err => console.debug('[labels] post failed:', err));
        } catch (e) {
            console.debug('[labels] dispatch failed:', e);
        }
    }
};
