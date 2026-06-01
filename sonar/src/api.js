/**
 * API client for the EchoLocate vector service.
 * Ported from the legacy frontend/api.js. The Firestore search cache is omitted
 * here (live requests only); add it back if cold-search latency becomes an issue.
 */

const BASE_URL = import.meta.env.VITE_VECTOR_API_URL || '';

async function request(method, path, body = null, params = null) {
  let url = `${BASE_URL}${path}`;
  if (params) url += `?${new URLSearchParams(params)}`;

  const options = { method, headers: { 'Content-Type': 'application/json' } };
  if (body) options.body = JSON.stringify(body);

  const response = await fetch(url, options);
  if (!response.ok) throw new Error(`API error: ${response.status}`);
  return response.json();
}

export const API = {
  baseUrl: BASE_URL,

  // Text search by artist/title/album
  textSearch(query, source = 'fma', limit = 50) {
    return request('GET', '/search', null, { query, source, limit });
  },

  // Semantic (vibe) search. Returns { results, original_query, enhanced_query? }.
  semanticSearch(query, source = 'fma', limit = 50, enhance = false) {
    return request('POST', '/semantic-search', { query, source, limit, enhance });
  },

  getTracks(limit = 50, source = 'fma') {
    return request('GET', '/tracks', null, { limit, source, random: true });
  },

  findSimilar(trackId, source = 'fma', limit = 14) {
    return request('GET', `/tracks/${trackId}/similar`, null, { source, limit });
  },

  findDissimilar(trackId, source = 'fma', limit = 14) {
    return request('GET', `/tracks/${trackId}/dissimilar`, null, { source, limit });
  },

  interpolatePlaylist(trackId1, trackId2, limit = 8, method = 'greedy_walk', source = 'fma', steerTrackIds = []) {
    const body = { track_id_1: trackId1, track_id_2: trackId2, limit, method, source };
    if (steerTrackIds.length) body.steer_track_ids = steerTrackIds;
    return request('POST', '/interpolate/playlist', body);
  },

  // Candidate tracks "between" two tracks (midpoint k-NN). Returns SearchResult[]
  // with x,y backfilled. Used to fill the line between two trail tracks.
  interpolate(trackId1, trackId2, method = 'slerp', limit = 8) {
    return request('POST', '/interpolate', { track_id_1: trackId1, track_id_2: trackId2, method, limit });
  },

  // Sampled backdrop of {id, x, y} for the dimmed sonar field.
  mapBackdrop(source = 'fma', n = 400) {
    return request('GET', '/map/backdrop', null, { source, n });
  },

  getStreamUrl(trackId) {
    return `${BASE_URL}/stream/${trackId}`;
  },

  getVersion() {
    return request('GET', '/version');
  },

  // Fire-and-forget label/search-event logging (training signal). Never throws.
  logSearchEvent(payload) {
    this._fireAndForget('/labels/search', payload);
  },
  logLabelEvent(payload) {
    this._fireAndForget('/labels/result', payload);
  },
  _fireAndForget(path, payload) {
    try {
      fetch(`${BASE_URL}${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        keepalive: true,
        credentials: 'omit',
        mode: 'cors',
      }).catch(() => {});
    } catch {
      /* ignore */
    }
  },
};
