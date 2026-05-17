import { SIGNAL_META, SIGNAL_ORDER } from "../lib/signals.js";

const ENDPOINTS = [
  "/semantic-search",
  "/search",
  "/tracks/{id}/similar",
  "/tracks/{id}/dissimilar",
  "/interpolate/playlist",
];

const PILL_BG = "#1a1a25";
const LABEL_STYLE = { fontSize: 10, textTransform: "uppercase", letterSpacing: 0.6, color: "#7a7a8a", marginRight: 6 };
const CTRL_STYLE = {
  background: PILL_BG, color: "#f0f0f5",
  border: "1px solid rgba(255,255,255,0.08)",
  borderRadius: 6, padding: "4px 8px",
  fontSize: 12, fontFamily: "inherit", outline: "none",
};

export default function FilterBar({ filters, setFilters, versions = [] }) {
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 10,
      padding: "6px 12px",
      background: "#12121a",
      borderBottom: "1px solid rgba(255,255,255,0.08)",
      flexWrap: "wrap",
      flexShrink: 0,
    }}>
      <div style={{ display: "flex", alignItems: "center" }}>
        <span style={LABEL_STYLE}>Range</span>
        <div style={{ display: "inline-flex", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 6, overflow: "hidden" }}>
          {[
            { v: 1, l: "24h" }, { v: 3, l: "3d" }, { v: 7, l: "7d" }, { v: 14, l: "14d" },
          ].map((opt) => (
            <button key={opt.v} type="button"
              onClick={() => setFilters({ ...filters, days: opt.v })}
              style={{
                padding: "4px 10px", fontSize: 12, fontFamily: "inherit",
                border: "none", cursor: "pointer",
                background: filters.days === opt.v ? "rgba(99,102,241,0.20)" : "transparent",
                color: filters.days === opt.v ? "#f0f0f5" : "#a0a0b0",
                borderRight: "1px solid rgba(255,255,255,0.06)",
                fontVariantNumeric: "tabular-nums",
              }}>{opt.l}</button>
          ))}
        </div>
      </div>

      <div style={{ display: "flex", alignItems: "center" }}>
        <span style={LABEL_STYLE}>Endpoint</span>
        <select value={filters.endpoint}
                onChange={(e) => setFilters({ ...filters, endpoint: e.target.value })}
                style={CTRL_STYLE}>
          <option value="">all</option>
          {ENDPOINTS.map((ep) => <option key={ep} value={ep}>{ep}</option>)}
        </select>
      </div>

      <div style={{ display: "flex", alignItems: "center" }}>
        <span style={LABEL_STYLE}>Version</span>
        <select value={filters.version}
                onChange={(e) => setFilters({ ...filters, version: e.target.value })}
                style={CTRL_STYLE}>
          <option value="">all</option>
          {versions.map((v) => <option key={v} value={v}>{v}</option>)}
        </select>
      </div>

      <div style={{ display: "flex", alignItems: "center" }}>
        <span style={LABEL_STYLE}>Signal</span>
        <div style={{ display: "inline-flex", gap: 4 }}>
          {SIGNAL_ORDER.map((s) => {
            const on = filters.signals.includes(s);
            const m = SIGNAL_META[s];
            return (
              <button key={s} type="button" title={s}
                onClick={() => {
                  const next = on ? filters.signals.filter((x) => x !== s) : [...filters.signals, s];
                  setFilters({ ...filters, signals: next });
                }}
                style={{
                  padding: "2px 8px", fontSize: 11, cursor: "pointer",
                  background: on ? m.bg : "transparent",
                  color: on ? m.color : "#7a7a8a",
                  border: `1px solid ${on ? m.color + "55" : "rgba(255,255,255,0.08)"}`,
                  borderRadius: 4, fontFamily: "inherit",
                  textTransform: "lowercase", fontWeight: 600,
                }}>
                <span style={{ fontFamily: "ui-monospace, SF Mono, Menlo, monospace", marginRight: 4 }}>{m.glyph}</span>
                {s}
              </button>
            );
          })}
        </div>
      </div>

      <div style={{ flex: 1 }} />
      <div style={{ display: "flex", alignItems: "center", gap: 8, color: "#7a7a8a", fontSize: 11, fontVariantNumeric: "tabular-nums" }}>
        <span style={{ width: 6, height: 6, borderRadius: 999, background: "#2e8b57", boxShadow: "0 0 6px #2e8b57" }} />
        live
      </div>
    </div>
  );
}
