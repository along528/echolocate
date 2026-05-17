import { useEffect, useMemo, useState } from "react";
import Header from "./components/Header.jsx";
import FilterBar from "./components/FilterBar.jsx";
import MetricsStrip from "./components/MetricsStrip.jsx";
import Feed from "./components/Feed.jsx";
import DetailPanel from "./components/DetailPanel.jsx";
import { useEvents } from "./hooks/useEvents.js";
import { useTrackCache } from "./hooks/useTrackCache.js";
import { computeStats } from "./lib/aggregate.js";
import { SIGNAL_ORDER } from "./lib/signals.js";

const INITIAL_FILTERS = {
  days: 7,
  endpoint: "",
  version: "",
  signals: [...SIGNAL_ORDER],
};

export default function App() {
  const [filters, setFilters] = useState(INITIAL_FILTERS);
  const [selectedLabelId, setSelectedLabelId] = useState(null);
  const [feedTab, setFeedTab] = useState("feed");
  const [metricsOpen, setMetricsOpen] = useState(true);
  const [now, setNow] = useState(() => Date.now());

  // Tick "now" once a minute so relative timestamps stay fresh.
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 60_000);
    return () => clearInterval(id);
  }, []);

  const { searches, labels, searchById } = useEvents(filters);

  // Discover all versions that appear in fetched searches so the dropdown reflects reality.
  const versions = useMemo(() => {
    const seen = new Set();
    for (const s of searches) {
      const m = s.versions?.model, i = s.versions?.index;
      if (m && i) seen.add(`${m} · ${i}`);
    }
    return Array.from(seen).sort();
  }, [searches]);

  // Client-side signal filter on top of server-side filters.
  const signalFiltered = useMemo(() => {
    if (filters.signals.length === SIGNAL_ORDER.length) return labels;
    return labels.filter((l) => filters.signals.includes(l.signal));
  }, [labels, filters.signals]);

  // Sorted, tab-applied feed view (desc by timestamp).
  const sortedLabels = useMemo(() => {
    let ls = [...signalFiltered].sort((a, b) => b.timestamp.localeCompare(a.timestamp));
    if (feedTab === "notes-only") ls = ls.filter((l) => l.note);
    return ls;
  }, [signalFiltered, feedTab]);

  // Selection invalidation: snap to first row when current selection drops out.
  useEffect(() => {
    if (!sortedLabels.length) {
      if (selectedLabelId) setSelectedLabelId(null);
      return;
    }
    const stillThere = sortedLabels.some((l) => l.label_id === selectedLabelId);
    if (!stillThere) setSelectedLabelId(sortedLabels[0].label_id);
  }, [sortedLabels, selectedLabelId]);

  const selected = sortedLabels.find((l) => l.label_id === selectedLabelId) || null;
  const stats = useMemo(() => computeStats(signalFiltered, searches), [signalFiltered, searches]);

  // Track ids needed for current view: feed rows, ranked-list of selected search, and seed/pair refs.
  const neededIds = useMemo(() => {
    const ids = new Set();
    for (const l of sortedLabels.slice(0, 200)) ids.add(l.track_id);
    if (selected) {
      const s = searchById[selected.search_id];
      if (s?.results) for (const r of s.results) ids.add(r.id);
      const q = s?.query;
      if (q?.seed_track_id) ids.add(q.seed_track_id);
      if (Array.isArray(q?.pair_track_ids)) for (const id of q.pair_track_ids) ids.add(id);
    }
    return Array.from(ids).filter(Boolean);
  }, [sortedLabels, selected, searchById]);

  const { trackById } = useTrackCache(neededIds);

  const totals = {
    feed: signalFiltered.length,
    "notes-only": signalFiltered.filter((l) => l.note).length,
  };

  const siblingLabels = selected
    ? labels.filter((l) => l.search_id === selected.search_id)
    : [];

  return (
    <div style={{
      background: "#0a0a0f", color: "#f0f0f5",
      fontFamily: "Inter, sans-serif", height: "100%",
      display: "flex", flexDirection: "column", overflow: "hidden",
    }}>
      <Header stats={stats} />
      <FilterBar filters={filters} setFilters={setFilters} versions={versions} />
      <MetricsStrip
        labels={signalFiltered} searches={searches}
        open={metricsOpen} onToggle={() => setMetricsOpen((o) => !o)}
      />
      <div style={{
        display: "grid",
        gridTemplateColumns: "minmax(0, 460px) minmax(0, 1fr)",
        flex: 1, minHeight: 0,
      }}>
        <Feed
          items={sortedLabels}
          activeTab={feedTab} setActiveTab={setFeedTab}
          totals={totals}
          selectedId={selectedLabelId} onSelect={setSelectedLabelId}
          trackById={trackById}
          searchById={searchById}
          now={now}
        />
        <div style={{ display: "flex", flexDirection: "column", minWidth: 0, background: "#0a0a0f" }}>
          {selected ? (
            <DetailPanel
              label={selected}
              search={searchById[selected.search_id]}
              siblingLabels={siblingLabels}
              trackById={trackById}
              now={now}
            />
          ) : (
            <div style={{ padding: 40, color: "#7a7a8a", fontStyle: "italic" }}>
              Select a label.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
