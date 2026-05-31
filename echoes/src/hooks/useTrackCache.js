import { useEffect, useRef, useState } from "react";
import { fetchTracks } from "../lib/api.js";

/**
 * useTrackCache(needIds)
 * Batch-fetches /tracks/by-ids (source="fma") for any id in `needIds` not
 * already cached. Returns { trackById, fetching }. trackById is a stable
 * Object map.
 */
export function useTrackCache(needIds) {
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

    // No cancellation: a returned response is always valid data and we MUST
    // release these ids from fetchingRef in every path. (A prior version
    // short-circuited on a `cancelled` flag, which leaked ids into
    // fetchingRef whenever the effect re-fired before the response landed —
    // those ids then got filtered out of `unknown` forever and never showed
    // their titles.)
    (async () => {
      try {
        const rows = await fetchTracks(unknown, "fma");
        const got = new Set();
        for (const r of rows) {
          cacheRef.current[r.id] = r;
          got.add(r.id);
        }
        for (const id of unknown) {
          if (!got.has(id)) cacheRef.current[id] = "missing";
        }
        setTick((n) => n + 1);
      } catch {
        // swallow; ids stay uncached and will be retried on the next
        // needIds change.
      } finally {
        for (const id of unknown) fetchingRef.current.delete(id);
      }
    })();
  }, [needIds.join(",")]);

  // Hide "missing" sentinel from callers — they just see undefined.
  const view = {};
  for (const [k, v] of Object.entries(cacheRef.current)) {
    if (v !== "missing") view[k] = v;
  }
  return { trackById: view };
}
