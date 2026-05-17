import FeedRow from "./FeedRow.jsx";

const MAX_ROWS = 200;

export default function Feed({ items, activeTab, setActiveTab, totals, selectedId, onSelect, trackById, searchById, now }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", borderRight: "1px solid rgba(255,255,255,0.08)", minWidth: 0 }}>
      <Tabs active={activeTab} onChange={setActiveTab} totals={totals} />
      <div style={{ overflowY: "auto", flex: 1 }}>
        {items.slice(0, MAX_ROWS).map((l) => (
          <FeedRow key={l.label_id} label={l}
            active={selectedId === l.label_id}
            onClick={() => onSelect(l.label_id)}
            trackById={trackById}
            searchById={searchById}
            now={now}
          />
        ))}
        {items.length === 0 && (
          <div style={{ padding: 32, color: "#7a7a8a", fontStyle: "italic", textAlign: "center" }}>
            No labels match the current filters.
          </div>
        )}
        {items.length > MAX_ROWS && (
          <div style={{ padding: "12px 14px", color: "#7a7a8a", fontSize: 11, textAlign: "center",
                        borderTop: "1px solid rgba(255,255,255,0.05)" }}>
            showing {MAX_ROWS} of {items.length}
          </div>
        )}
      </div>
    </div>
  );
}

function Tabs({ active, onChange, totals }) {
  const tabs = [
    { k: "feed", l: "All Labels" },
    { k: "notes-only", l: "With Notes" },
  ];
  return (
    <div style={{
      display: "flex", alignItems: "center",
      padding: "0 12px",
      borderBottom: "1px solid rgba(255,255,255,0.08)",
      background: "#0e0e15",
      height: 36, flexShrink: 0,
    }}>
      {tabs.map((t) => (
        <button key={t.k} type="button" onClick={() => onChange(t.k)}
          style={{
            background: "none", border: "none", cursor: "pointer",
            color: active === t.k ? "#f0f0f5" : "#7a7a8a",
            fontSize: 12, fontWeight: 500, padding: "8px 12px",
            position: "relative", fontFamily: "inherit",
            display: "flex", alignItems: "center", gap: 6,
          }}>
          {t.l}
          <span style={{
            fontSize: 10, color: "#5a5a6c", fontVariantNumeric: "tabular-nums",
            padding: "1px 6px", background: "rgba(255,255,255,0.04)", borderRadius: 4,
          }}>{totals[t.k] ?? 0}</span>
          {active === t.k && (
            <span style={{ position: "absolute", bottom: -1, left: 12, right: 12, height: 2, background: "#6366f1" }} />
          )}
        </button>
      ))}
      <div style={{ flex: 1 }} />
      <span style={{ fontSize: 10, color: "#5a5a6c", letterSpacing: 0.5, textTransform: "uppercase" }}>
        newest first
      </span>
    </div>
  );
}
