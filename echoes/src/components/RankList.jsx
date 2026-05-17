import { useEffect, useRef } from "react";
import SignalPill from "./SignalPill.jsx";

export default function RankList({ search, labelsByRank, focusTrackId, trackById }) {
  const focusRef = useRef(null);
  const scrollerRef = useRef(null);

  useEffect(() => {
    const el = focusRef.current;
    const scroller = scrollerRef.current;
    if (el && scroller) {
      scroller.scrollTop = el.offsetTop - 100;
    }
  }, [focusTrackId]);

  if (!search?.results?.length) {
    return (
      <div style={{ padding: "10px 20px 16px", fontSize: 11, color: "#7a7a8a", fontStyle: "italic" }}>
        No ranked results in this search.
      </div>
    );
  }

  return (
    <div ref={scrollerRef} style={{ maxHeight: 380, overflowY: "auto", padding: "0 8px 12px", marginTop: 4 }}>
      {search.results.map((r) => {
        const tr = trackById[r.id];
        const lab = labelsByRank[r.rank];
        const focused = r.id === focusTrackId;
        return (
          <div key={`${r.id}-${r.rank}`} ref={focused ? focusRef : null} style={{
            display: "grid",
            gridTemplateColumns: "32px 1fr auto",
            gap: 10, padding: "5px 10px",
            background: focused
              ? "rgba(99,102,241,0.12)"
              : (lab ? "rgba(255,255,255,0.02)" : "transparent"),
            borderRadius: 4,
            borderLeft: focused ? "2px solid #6366f1" : "2px solid transparent",
            alignItems: "center",
            marginBottom: 1,
          }}>
            <div style={{
              fontFamily: "ui-monospace, SF Mono, Menlo, monospace",
              fontSize: 11, color: "#5a5a6c", textAlign: "right",
              fontVariantNumeric: "tabular-nums",
            }}>{r.rank}</div>
            <div style={{ minWidth: 0 }}>
              <div style={{
                fontSize: 12, color: focused ? "#f0f0f5" : "#d0d0d8",
                whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                fontWeight: focused ? 600 : 400,
              }}>{tr ? tr.title : r.id}</div>
              <div style={{
                fontSize: 10, color: "#7a7a8a",
                whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
              }}>{tr ? tr.artist : ""}</div>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              {lab && <SignalPill signal={lab.signal} size="xs" />}
              {lab && lab.note && (
                <span title={lab.note} style={{ color: "#a78bfa", fontSize: 10, fontFamily: "ui-monospace, SF Mono, Menlo, monospace" }}>
                  ·note·
                </span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
