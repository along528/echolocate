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

    // Semantic search with natural language
    async semanticSearch(query, source = 'fma', limit = 50, enhance = false) {
        return this.request('POST', '/semantic-search', { query, source, limit, enhance });
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
    async interpolatePlaylist(trackId1, trackId2, limit = 10, method = 'greedy_walk', source = 'all', steerTrackId = null) {
        return this.request('POST', '/interpolate/playlist', {
            track_id_1: trackId1,
            track_id_2: trackId2,
            limit,
            method,
            source,
            steer_track_id: steerTrackId
        });
    },

    // Get stream URL for a track
    getStreamUrl(trackId) {
        return `${this.baseUrl}/stream/${trackId}`;
    }
};
