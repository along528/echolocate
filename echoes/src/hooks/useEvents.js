import { useEffect, useRef, useState } from "react";
import { fetchEvents } from "../lib/api.js";

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

// Newest label per (search_id, track_id) wins — user's latest action is canonical.
// A user re-labeling a track (e.g. relevant → negative, or note edited) replaces
// the prior entry; downstream counts, charts, and the feed should reflect that.
function collapseLabels(arr) {
  const byKey = new Map();
  for (const l of arr) {
    const k = `${l.search_id}|${l.track_id}`;
    const prev = byKey.get(k);
    if (!prev || l.timestamp > prev.timestamp) byKey.set(k, l);
  }
  return Array.from(byKey.values()).sort((a, b) =>
    b.timestamp < a.timestamp ? -1 : b.timestamp > a.timestamp ? 1 : 0,
  );
}

/**
 * useEvents(filters)
 *   filters: { days, endpoint, version }   // signal filter is client-side
 *   version: "" or "model · index"
 *
 * Returns: { searches, labels, searchById, loading, error }
 *
 * Behavior: paginated fetch on filter change. Labels are collapsed by
 * (search_id, track_id) with newest-wins so every consumer sees the user's
 * current intent rather than the raw event log.
 */
export function useEvents(filters) {
  const [searches, setSearches] = useState([]);
  const [labels, setLabels] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

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
          // Stream into the UI as pages arrive (labels collapsed on every page so
          // the visible counts are consistent during the fetch).
          setSearches([...accSearches]);
          setLabels(collapseLabels(accLabels));
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

  // Derive a search-by-id index for the detail panel.
  const searchById = {};
  for (const s of searches) searchById[s.search_id] = s;

  return { searches, labels, searchById, loading, error };
}
