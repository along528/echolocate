/**
 * Firestore-based cache for semantic search results.
 * Uses the same deterministic hashing as populate_cache.py
 * so that pre-populated results are found by the frontend.
 */

const SearchCache = {
    db: null,
    COLLECTION: 'semantic_search_cache',

    /**
     * Initialize Firebase and Firestore.
     * Call once at app startup.
     */
    init() {
        try {
            const firebaseConfig = {
                projectId: 'cloud-crate-485418',
            };
            // Use firebase compat (loaded via CDN in index.html)
            if (!firebase.apps.length) {
                firebase.initializeApp(firebaseConfig);
            }
            this.db = firebase.firestore();
            console.log('[SearchCache] Firestore initialized');
        } catch (e) {
            console.warn('[SearchCache] Failed to initialize Firestore:', e);
        }
    },

    /**
     * Build the same cache key used by populate_cache.py:
     * SHA-256 of JSON.stringify({enhance, limit, query, source}) with sorted keys.
     */
    async _cacheKey(query, source, limit, enhance) {
        const obj = { enhance: !!enhance, limit, query, source };
        const raw = JSON.stringify(obj);
        const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(raw));
        return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, '0')).join('');
    },

    /**
     * Look up a cached response.
     * Returns the full SemanticSearchResponse object or null on miss.
     */
    async get(query, source, limit, enhance) {
        if (!this.db) return null;
        try {
            const key = await this._cacheKey(query, source, limit, enhance);
            const doc = await this.db.collection(this.COLLECTION).doc(key).get();
            if (doc.exists) {
                const data = doc.data();
                console.log(`[SearchCache] HIT for "${query}"`);
                return data.response;
            }
            console.log(`[SearchCache] MISS for "${query}"`);
            return null;
        } catch (e) {
            console.warn('[SearchCache] Lookup failed:', e);
            return null;
        }
    },
};
