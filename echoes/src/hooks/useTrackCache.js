import { useEffect, useRef, useState } from "react";
import { fetchTracks } from "../lib/api.js";

/**
 * useTrackCache(needIds)
 * Batch-fetches /tracks/by-ids for any id in `needIds` not already cached.
 * Returns { trackById, fetching }. trackById is a stable Object map.
 */
export function useTrackCache(needIds, source = "fma") {
  const cacheRef = useRef({});       // id -> track | "missing"
  const [, setTick] = useState(0);
  const fetchingRef = useRef(new Set());

  useEffect(() => {
    if (!needIds || !needIds.length) return;
    const unknown = needIds.filter(
      (id) => id && !cacheRef.current[id] && !fetchingRef.current.has(id),
    );
    if (!unknown.length) return;
    for (const id of unknown) fetchingRef.current.add(id);

    let cancelled = false;
    (async () => {
      try {
        const rows = await fetchTracks(unknown, source);
        if (cancelled) return;
        const got = new Set();
        for (const r of rows) {
          cacheRef.current[r.id] = r;
          got.add(r.id);
        }
        for (const id of unknown) {
          if (!got.has(id)) cacheRef.current[id] = "missing";
          fetchingRef.current.delete(id);
        }
        setTick((n) => n + 1);
      } catch {
        for (const id of unknown) fetchingRef.current.delete(id);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [needIds.join(","), source]);

  // Hide "missing" sentinel from callers — they just see undefined.
  const view = {};
  for (const [k, v] of Object.entries(cacheRef.current)) {
    if (v !== "missing") view[k] = v;
  }
  return { trackById: view };
}
