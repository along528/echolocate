import { SIGNAL_META } from "../lib/signals.js";
import { fmtRelative } from "../lib/format.js";
import { queryToString } from "../lib/query.js";
import Chip from "./Chip.jsx";

export default function FeedRow({ label, active, onClick, trackById, searchById, now }) {
  const search = searchById[label.search_id];
  const tr = trackById[label.track_id];
  const m = SIGNAL_META[label.signal] || SIGNAL_META.cleared;
  const endpointChip = search?.endpoint
    ? search.endpoint.replace(/\{id\}/, "·")
    : "—";

  return (
    <div onClick={onClick} style={{
      padding: "8px 14px 9px",
      borderBottom: "1px solid rgba(255,255,255,0.04)",
      cursor: "pointer",
      background: active ? "rgba(99,102,241,0.10)" : "transparent",
      borderLeft: active ? "2px solid #6366f1" : "2px solid transparent",
      transition: "background 0.12s",
      display: "grid",
      gridTemplateColumns: "auto 1fr auto",
      gap: 10,
      alignItems: "start",
    }}>
      <div style={{
        width: 24, height: 24, borderRadius: 4,
        background: m.bg, color: m.color,
        display: "flex", alignItems: "center", justifyContent: "center",
        fontFamily: "ui-monospace, SF Mono, Menlo, monospace",
        fontSize: 14, fontWeight: 700, flexShrink: 0,
        marginTop: 1,
      }}>{m.glyph}</div>
      <div style={{ minWidth: 0 }}>
        <div style={{
          fontSize: 13, fontWeight: 500, color: "#f0f0f5",
          whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
        }}>{tr ? tr.title : label.track_id}</div>
        <div style={{
          fontSize: 11, color: "#7a7a8a", marginTop: 1,
          whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
        }}>
          <span style={{ color: "#a0a0b0" }}>{tr ? tr.artist : ""}</span>
          <span> · rank {label.rank === -1 ? "?" : label.rank}</span>
          <span> · {queryToString(search, trackById)}</span>
        </div>
        {label.note && (
          <div style={{
            fontSize: 11, marginTop: 4, color: "#e0e0ea",
            fontStyle: "italic",
            paddingLeft: 8,
            borderLeft: `2px solid ${m.color}`,
            whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
          }}>{`"${label.note}"`}</div>
        )}
      </div>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4, flexShrink: 0 }}>
        <span style={{ fontSize: 10, color: "#7a7a8a", fontVariantNumeric: "tabular-nums" }}>
          {fmtRelative(label.timestamp, now)}
        </span>
        <Chip>{endpointChip}</Chip>
      </div>
    </div>
  );
}
