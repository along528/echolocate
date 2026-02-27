#!/usr/bin/env python3
"""
Populate Firestore semantic_search_cache by querying the deployed vector-rs service
for every seed query. Uses the same cache-key hashing as cache.js.
"""

import hashlib
import json
import time
from datetime import datetime, timezone

import requests
from google.cloud import firestore

VECTOR_RS_URL = "https://cloud-crate-vector-rs-403961692263.us-central1.run.app"
COLLECTION = "semantic_search_cache"

# Default search parameters matching frontend behaviour
DEFAULT_SOURCE = "fma"
DEFAULT_LIMIT = 50
DEFAULT_ENHANCE = True


def cache_key(query: str, source: str, limit: int, enhance: bool) -> str:
    """Deterministic SHA-256 key matching cache.js _cacheKey()."""
    obj = {"enhance": enhance, "limit": limit, "query": query, "source": source}
    raw = json.dumps(obj, sort_keys=False)  # keys already in sorted order
    return hashlib.sha256(raw.encode()).hexdigest()


def main():
    # Load shared seed queries
    with open("seed_queries.json") as f:
        queries = json.load(f)

    db = firestore.Client()
    col = db.collection(COLLECTION)

    print(f"Populating cache for {len(queries)} queries against {VECTOR_RS_URL}")
    print(f"  source={DEFAULT_SOURCE}  limit={DEFAULT_LIMIT}  enhance={DEFAULT_ENHANCE}")
    print()

    for i, query in enumerate(queries, 1):
        key = cache_key(query, DEFAULT_SOURCE, DEFAULT_LIMIT, DEFAULT_ENHANCE)
        print(f"[{i}/{len(queries)}] {query!r} -> {key[:12]}...", end=" ", flush=True)

        try:
            resp = requests.post(
                f"{VECTOR_RS_URL}/semantic-search",
                json={
                    "query": query,
                    "source": DEFAULT_SOURCE,
                    "limit": DEFAULT_LIMIT,
                    "enhance": DEFAULT_ENHANCE,
                },
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()

            col.document(key).set({
                "query": query,
                "source": DEFAULT_SOURCE,
                "limit": DEFAULT_LIMIT,
                "enhance": DEFAULT_ENHANCE,
                "response": data,
                "cached_at": datetime.now(timezone.utc),
            })

            n_results = len(data.get("results", []))
            print(f"✓ ({n_results} results)")

        except Exception as e:
            print(f"✗ {e}")

        # Be gentle with the service
        time.sleep(0.5)

    print("\nDone!")


if __name__ == "__main__":
    main()
