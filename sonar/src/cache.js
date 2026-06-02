/**
 * Firestore cache for sonar — modular Firebase SDK port of the legacy
 * frontend/cache.js. Two responsibilities:
 *
 *   1. Semantic-search result cache (collection `semantic_search_cache`),
 *      keyed with the SAME SHA-256 hash as cache.js / populate_cache.py so
 *      pre-warmed results are shared with the legacy frontend.
 *   2. Suggested-chip vocabulary (collection `sonar_config`, doc `suggestions`,
 *      field `chips`) so the vibe suggestions can be curated server-side
 *      without a redeploy. Falls back to a baked-in list on any miss/error.
 */
import { initializeApp, getApps } from 'firebase/app';
import { getFirestore, doc, getDoc } from 'firebase/firestore';
// Single source of truth for the chip vocabulary, shared with
// sonar/populate_cache.py so the warmed cache keys line up.
import SUGGESTED_CHIPS from './suggested_chips.json';

const FIREBASE_CONFIG = { projectId: 'cloud-crate-485418' };
const SEARCH_COLLECTION = 'semantic_search_cache';
const CONFIG_COLLECTION = 'sonar_config';
const SUGGESTIONS_DOC = 'suggestions';

// Baked-in fallback vibe vocabulary (used when Firestore is unavailable).
export const FALLBACK_SUGGESTIONS = SUGGESTED_CHIPS;

let _db = null;

function db() {
  if (_db) return _db;
  try {
    const app = getApps().length ? getApps()[0] : initializeApp(FIREBASE_CONFIG);
    _db = getFirestore(app);
  } catch (e) {
    console.warn('[Cache] Firestore init failed:', e);
    _db = null;
  }
  return _db;
}

// SHA-256 of JSON.stringify({enhance, limit, query, source}) with sorted keys —
// byte-for-byte identical to legacy cache.js _cacheKey / populate_cache.py.
async function cacheKey(query, source, limit, enhance) {
  const obj = { enhance: !!enhance, limit, query, source };
  const raw = JSON.stringify(obj);
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(raw));
  return Array.from(new Uint8Array(buf)).map((b) => b.toString(16).padStart(2, '0')).join('');
}

export const Cache = {
  // Look up a cached semantic-search response. Returns the response object or null.
  async getSearch(query, source, limit, enhance) {
    const d = db();
    if (!d) return null;
    try {
      const key = await cacheKey(query, source, limit, enhance);
      const snap = await getDoc(doc(d, SEARCH_COLLECTION, key));
      return snap.exists() ? snap.data().response : null;
    } catch (e) {
      console.warn('[Cache] search lookup failed:', e);
      return null;
    }
  },

  // Fetch the curated suggestion list; falls back to FALLBACK_SUGGESTIONS.
  async getSuggestions() {
    const d = db();
    if (!d) return FALLBACK_SUGGESTIONS;
    try {
      const snap = await getDoc(doc(d, CONFIG_COLLECTION, SUGGESTIONS_DOC));
      const chips = snap.exists() ? snap.data().chips : null;
      return Array.isArray(chips) && chips.length ? chips : FALLBACK_SUGGESTIONS;
    } catch (e) {
      console.warn('[Cache] suggestions lookup failed:', e);
      return FALLBACK_SUGGESTIONS;
    }
  },
};
