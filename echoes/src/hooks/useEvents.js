import { useEffect, useRef, useState } from "react";
import { fetchEvents, fetchSince } from "../lib/api.js";

const POLL_MS = 5000;
const PAGE_LIMIT = 500;
const HARD_CEILING = 5000;

function splitEvents(arr) {
  const searches = [];
  const labels = [];
  for (const e of arr) {
    if (e.type === "search") searches.push(e);
    else if (e.type === "label") labels.push(e);
  }
  return { searches, labels };
}

function mergeUnique(prev, next, idField) {
  const seen = new Set(prev.map((e) => e[idField]));
  const out = prev.slice();
  for (const e of next) {
    if (!seen.has(e[idField])) {
      seen.add(e[idField]);
      out.push(e);
    }
  }
  return out;
}

/**
 * useEvents(filters)
 *   filters: { days, endpoint, version }   // signal filter is client-side
 *   version: "" or "model · index"
 *
 * Returns: { searches, labels, searchById, loading, error }
 *
 * Behavior: initial paginated fetch on filter change; then 5s polling for new
 * events via `since=<newest_ts>`. Polling preserves existing items.
 */
export function useEvents(filters) {
  const [searches, setSearches] = useState([]);
  const [labels, setLabels] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Newest timestamp we've seen — drives the `since` poll.
  const newestRef = useRef(null);
  const aliveRef = useRef(0); // bump on filter change to cancel in-flight pagers

  // Stable filter key for effect dependency.
  const key = JSON.stringify({
    days: filters.days,
    endpoint: filters.endpoint,
    version: filters.version,
  });

  useEffect(() => {
    aliveRef.current += 1;
    const myEpoch = aliveRef.current;
    setLoading(true);
    setError(null);
    setSearches([]);
    setLabels([]);
    newestRef.current = null;

    const now = Date.now();
    const from = new Date(now - filters.days * 86_400_000).toISOString();
    const to = new Date(now).toISOString();

    let [model, index] = ["", ""];
    if (filters.version) {
      const parts = filters.version.split(" · ");
      model = parts[0] || "";
      index = parts[1] || "";
    }

    const baseParams = {
      from,
      to,
      endpoint: filters.endpoint || undefined,
      model: model || undefined,
      index: index || undefined,
      limit: PAGE_LIMIT,
    };

    (async () => {
      try {
        let cursor;
        let accSearches = [];
        let accLabels = [];
        let pagesFetched = 0;
        do {
          const { events, next_cursor } = await fetchEvents({ ...baseParams, cursor });
          if (myEpoch !== aliveRef.current) return; // cancelled by newer filter
          const { searches: s, labels: l } = splitEvents(events);
          accSearches = accSearches.concat(s);
          accLabels = accLabels.concat(l);
          if (events.length) {
            const newest = events[0].timestamp; // server returns desc-sorted
            if (!newestRef.current || newest > newestRef.current) {
              newestRef.current = newest;
            }
          }
          // Stream into the UI as pages arrive.
          setSearches([...accSearches]);
          setLabels([...accLabels]);
          cursor = next_cursor;
          pagesFetched += 1;
          if (pagesFetched * PAGE_LIMIT >= HARD_CEILING) break;
        } while (cursor);
        if (myEpoch === aliveRef.current) setLoading(false);
      } catch (e) {
        if (myEpoch === aliveRef.current) {
          setError(e.message || String(e));
          setLoading(false);
        }
      }
    })();
  }, [key, filters.days, filters.endpoint, filters.version]);

  // 5s `since` polling.
  useEffect(() => {
    const myEpoch = aliveRef.current;
    const id = setInterval(async () => {
      if (myEpoch !== aliveRef.current) return;
      // Skip when hidden — otherwise a forgotten tab keeps vector-rs's
      // Cloud Run instance warm 24/7.
      if (document.visibilityState !== "visible") return;
      const sinceIso = newestRef.current;
      if (!sinceIso) return;
      try {
        const { events } = await fetchSince(sinceIso, PAGE_LIMIT);
        if (myEpoch !== aliveRef.current) return;
        if (!events?.length) return;
        const { searches: s, labels: l } = splitEvents(events);
        if (s.length) {
          setSearches((prev) => {
            // Newest first; prepend new ones that aren't in prev.
            const fresh = s.filter((e) => !prev.some((p) => p.search_id === e.search_id));
            return fresh.concat(prev);
          });
        }
        if (l.length) {
          setLabels((prev) => {
            const fresh = l.filter((e) => !prev.some((p) => p.label_id === e.label_id));
            return fresh.concat(prev);
          });
        }
        const newestTs = events[0].timestamp;
        if (newestTs > sinceIso) newestRef.current = newestTs;
      } catch {
        // poll failures are silent — next tick will retry
      }
    }, POLL_MS);
    return () => clearInterval(id);
  }, [key]);

  // Derive a search-by-id index for the detail panel.
  const searchById = {};
  for (const s of searches) searchById[s.search_id] = s;

  return { searches, labels, searchById, loading, error };
}
