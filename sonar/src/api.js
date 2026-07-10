/**
 * API client for the EchoLocate vector service.
 * Ported from the legacy frontend/api.js, including the Firestore search cache
 * (see cache.js) so pre-warmed semantic results are shared with the legacy UI.
 */
import { Cache } from './cache.js';

const BASE_URL = import.meta.env.VITE_VECTOR_API_URL || '';

// Optional override for the vibe-chip score threshold (backend default 0.25).
// PR previews back onto the synthetic sample index, whose random vectors score
// ~0 against every vibe anchor — the preview build bakes -1 here so chips are
// visible. Unset in production builds.
const VIBES_MIN_SCORE = parseFloat(import.meta.env.VITE_VIBES_MIN_SCORE ?? '');

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
  // Checks the Firestore cache first (fast path), but always fires the live
  // request too so vector-rs stays warm — mirrors the legacy frontend.
  async semanticSearch(query, source = 'fma', limit = 50, enhance = false) {
    const live = request('POST', '/semantic-search', { query, source, limit, enhance });
    try {
      const cached = await Cache.getSearch(query, source, limit, enhance);
      if (cached) {
        live.catch(() => {}); // let warm-up finish in the background
        return cached;
      }
    } catch {
      /* fall through to live */
    }
    return live;
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
  // with x,y backfilled. Used to fill the line between two playlist tracks.
  // Constrained to FMA so interpolation only surfaces streamable FMA tracks.
  interpolate(trackId1, trackId2, method = 'slerp', limit = 8, source = 'fma') {
    return request('POST', '/interpolate', { track_id_1: trackId1, track_id_2: trackId2, method, limit, source });
  },

  // Sampled backdrop of {id, x, y} for the dimmed sonar field.
  mapBackdrop(source = 'fma', n = 400) {
    return request('GET', '/map/backdrop', null, { source, n });
  },

  // The single globally-nearest track to a clicked map coordinate (x,y in
  // [0,1]). Used for click-to-probe across the whole corpus — finds tracks not
  // currently loaded in the UI. Returns a TrackResponse.
  mapNearest(x, y, source = 'fma') {
    return request('GET', '/map/nearest', null, { x, y, source });
  },

  // Batch-hydrate live vibe chips for up to 500 tracks. Each returned row is a
  // TrackResponse plus vibes: [{vibe, score}] (absent while the backend's
  // anchor embeddings are still warming — treat as "no chips yet, no retry").
  getTracksVibes(ids) {
    const body = { ids, include_vibes: true };
    if (Number.isFinite(VIBES_MIN_SCORE)) body.vibes_min_score = VIBES_MIN_SCORE;
    return request('POST', '/tracks/by-ids', body);
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
