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
  days: 365,
  endpoint: "",
  version: "",
  query: "",
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

  // Client-side filters layered on top of server-side endpoint/version filters.
  // Endpoint and query are joined back via searchById since labels carry no endpoint/query themselves.
  const filteredLabels = useMemo(() => {
    const q = filters.query.trim().toLowerCase();
    const ep = filters.endpoint;
    const allSignals = filters.signals.length === SIGNAL_ORDER.length;
    return labels.filter((l) => {
      if (!allSignals && !filters.signals.includes(l.signal)) return false;
      if (!ep && !q) return true;
      const s = searchById[l.search_id];
      if (!s) return false;
      if (ep && s.endpoint !== ep) return false;
      if (q) {
        const text = s.query?.text;
        if (typeof text !== "string" || !text.toLowerCase().includes(q)) return false;
      }
      return true;
    });
  }, [labels, filters.signals, filters.endpoint, filters.query, searchById]);

  // Sorted, tab-applied feed view (desc by timestamp).
  const sortedLabels = useMemo(() => {
    let ls = [...filteredLabels].sort((a, b) => b.timestamp.localeCompare(a.timestamp));
    if (feedTab === "notes-only") ls = ls.filter((l) => l.note);
    return ls;
  }, [filteredLabels, feedTab]);

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
  const stats = useMemo(() => computeStats(filteredLabels, searches), [filteredLabels, searches]);

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
    feed: filteredLabels.length,
    "notes-only": filteredLabels.filter((l) => l.note).length,
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
        labels={filteredLabels} searches={searches}
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
          onQueryClick={(text) => setFilters((f) => ({ ...f, query: text }))}
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
