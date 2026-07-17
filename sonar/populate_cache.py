#!/usr/bin/env python3
"""
Warm the Firestore caches the sonar frontend reads from.

Two things, both optional and idempotent:

  1. semantic_search_cache — pre-compute /semantic-search results for every
     suggested chip so clicking a chip is instant. Uses the SAME cache-key
     hashing and document shape as the legacy frontend's populate_cache.py and
     cache.js (archived on the `legacy` branch), but
     with sonar's request params (limit=24, enhance=True by default) and sonar's
     short chip labels — otherwise the keys won't match what the frontend looks
     up.

  2. sonar_config/suggestions — optionally publish the chip list to Firestore so
     it can be curated without a redeploy (the frontend falls back to the baked-in
     list in src/suggested_chips.json when this doc is absent).

The chip list is read from src/suggested_chips.json (the same file the frontend
bundles), keeping a single source of truth.

Usage:
    python populate_cache.py                     # warm cache for all chips
    python populate_cache.py --write-suggestions # also publish the chip list
    python populate_cache.py --dry-run           # print keys, hit nothing
    python populate_cache.py --limit 24 --no-enhance

Requires application-default credentials for the Firestore project, e.g.:
    gcloud auth application-default login
"""

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# requests + google-cloud-firestore are imported lazily inside main() so that
# --dry-run works without them, and a real run prints a clear install hint:
#     pip install requests google-cloud-firestore

PROJECT_ID = "cloud-crate-485418"
VECTOR_RS_URL = "https://cloud-crate-vector-rs-403961692263.us-central1.run.app"
SEARCH_COLLECTION = "semantic_search_cache"
CONFIG_COLLECTION = "sonar_config"
SUGGESTIONS_DOC = "suggestions"

# Sonar's semantic-search params (must match API.semanticSearch in src/api.js:
# layer.query, source='fma', limit=24, enhance=true).
DEFAULT_SOURCE = "fma"
DEFAULT_LIMIT = 24
DEFAULT_ENHANCE = True

CHIPS_PATH = Path(__file__).parent / "src" / "suggested_chips.json"


def cache_key(query: str, source: str, limit: int, enhance: bool) -> str:
    """Deterministic SHA-256 key matching cache.js cacheKey() / populate_cache.py.

    Key order (enhance, limit, query, source) and compact separators mirror
    JS `JSON.stringify({ enhance, limit, query, source })` byte-for-byte.
    """
    obj = {"enhance": enhance, "limit": limit, "query": query, "source": source}
    raw = json.dumps(obj, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def load_chips() -> list[str]:
    with open(CHIPS_PATH) as f:
        chips = json.load(f)
    if not isinstance(chips, list) or not chips:
        raise SystemExit(f"No chips found in {CHIPS_PATH}")
    return chips


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                    help=f"result limit to cache (default {DEFAULT_LIMIT}; must match the frontend)")
    ap.add_argument("--source", default=DEFAULT_SOURCE, help=f"track source (default {DEFAULT_SOURCE})")
    ap.add_argument("--no-enhance", action="store_true", help="cache un-enhanced queries")
    ap.add_argument("--vector-url", default=VECTOR_RS_URL, help="vector-rs base URL")
    ap.add_argument("--project", default=PROJECT_ID, help="Firestore project id")
    ap.add_argument("--write-suggestions", action="store_true",
                    help=f"also write the chip list to {CONFIG_COLLECTION}/{SUGGESTIONS_DOC}")
    ap.add_argument("--dry-run", action="store_true",
                    help="compute keys and print plan, but don't call the service or write Firestore")
    args = ap.parse_args()

    enhance = not args.no_enhance
    chips = load_chips()

    print(f"Sonar cache warm-up: {len(chips)} chips from {CHIPS_PATH.name}")
    print(f"  source={args.source}  limit={args.limit}  enhance={enhance}")
    print(f"  vector={args.vector_url}")
    print(f"  project={args.project}{'  (DRY RUN)' if args.dry_run else ''}\n")

    requests = db = None
    if not args.dry_run:
        try:
            import requests  # noqa: F811
            from google.cloud import firestore
        except ImportError as e:
            raise SystemExit(
                f"Missing dependency ({e.name}). Install with:\n"
                "    pip install requests google-cloud-firestore"
            )
        db = firestore.Client(project=args.project)

    if args.write_suggestions:
        print(f"[suggestions] {CONFIG_COLLECTION}/{SUGGESTIONS_DOC} <- {len(chips)} chips", end=" ")
        if args.dry_run:
            print("(skipped)")
        else:
            db.collection(CONFIG_COLLECTION).document(SUGGESTIONS_DOC).set({
                "chips": chips,
                "updated_at": datetime.now(timezone.utc),
            })
            print("✓")
        print()

    col = None if args.dry_run else db.collection(SEARCH_COLLECTION)

    ok = 0
    for i, query in enumerate(chips, 1):
        key = cache_key(query, args.source, args.limit, enhance)
        print(f"[{i}/{len(chips)}] {query!r} -> {key[:12]}…", end=" ", flush=True)

        if args.dry_run:
            print("(dry run)")
            continue

        try:
            resp = requests.post(
                f"{args.vector_url}/semantic-search",
                json={"query": query, "source": args.source, "limit": args.limit, "enhance": enhance},
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()

            col.document(key).set({
                "query": query,
                "source": args.source,
                "limit": args.limit,
                "enhance": enhance,
                "response": data,
                "cached_at": datetime.now(timezone.utc),
            })
            n = len(data.get("results", []))
            print(f"✓ ({n} results)")
            ok += 1
        except Exception as e:  # noqa: BLE001 — best-effort warm-up, keep going
            print(f"✗ {e}", file=sys.stderr)

        time.sleep(0.5)  # be gentle with the service

    if not args.dry_run:
        print(f"\nDone — warmed {ok}/{len(chips)} chips.")


if __name__ == "__main__":
    main()
