import { SIGNAL_META } from "../lib/signals.js";
import { fmtDateTime, fmtRelative } from "../lib/format.js";
import { queryToString } from "../lib/query.js";
import SignalPill from "./SignalPill.jsx";
import Chip from "./Chip.jsx";
import Section from "./Section.jsx";
import KV from "./KV.jsx";
import RankList from "./RankList.jsx";

const MONO = "ui-monospace, SF Mono, Menlo, monospace";

export default function DetailPanel({ label, search, siblingLabels, trackById, now, onQueryClick }) {
  const isTextQuery = search?.query_kind === "text" && typeof search?.query?.text === "string";
  const tr = trackById[label.track_id];
  const m = SIGNAL_META[label.signal] || SIGNAL_META.cleared;
  const labelsByRank = {};
  for (const l of siblingLabels) labelsByRank[l.rank] = l;

  return (
    <div style={{ overflowY: "auto", height: "100%" }}>
      {/* Hero */}
      <div style={{ padding: "16px 20px 14px", borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
          <SignalPill signal={label.signal} size="lg" />
          <span style={{ fontSize: 11, color: "#7a7a8a", fontVariantNumeric: "tabular-nums" }}>
            {fmtDateTime(label.timestamp)} · {fmtRelative(label.timestamp, now)}
          </span>
          <div style={{ flex: 1 }} />
          <span style={{ fontSize: 10, color: "#5a5a6c", fontFamily: MONO }}>
            {label.label_id.slice(0, 24)}…
          </span>
        </div>
        <div style={{ fontSize: 19, fontWeight: 600, color: "#f0f0f5", letterSpacing: "-0.01em", marginTop: 8 }}>
          {tr ? tr.title : label.track_id}
        </div>
        <div style={{ fontSize: 13, color: "#a0a0b0", marginTop: 2 }}>
          {tr ? `${tr.artist} — ${tr.album}` : "—"}
        </div>
        <div style={{ display: "flex", gap: 12, marginTop: 10, fontSize: 11, color: "#7a7a8a" }}>
          <span>
            <span style={{ color: "#5a5a6c" }}>track_id</span>{" "}
            <span style={{ fontFamily: MONO, color: "#a0a0b0" }}>{label.track_id}</span>
          </span>
          <span>
            <span style={{ color: "#5a5a6c" }}>rank</span>{" "}
            <span style={{ fontFamily: MONO, color: "#a0a0b0" }}>
              {label.rank === -1 ? "?" : label.rank}
            </span>
          </span>
        </div>
        {label.note && (
          <div style={{
            marginTop: 14, padding: "10px 12px", borderRadius: 6,
            background: m.bg, borderLeft: `2px solid ${m.color}`,
            fontSize: 13, color: "#f0f0f5", fontStyle: "italic",
            lineHeight: 1.4,
          }}>{`"${label.note}"`}</div>
        )}
      </div>

      {/* Parent search */}
      <Section title="Parent Search">
        <div style={{ padding: "0 20px 16px" }}>
          {search ? (
            <>
              <KV k="query_kind"><Chip tone="indigo">{search.query_kind}</Chip></KV>
              <KV k="endpoint">
                <span style={{ fontFamily: MONO, color: "#a0a0b0" }}>{search.endpoint}</span>
              </KV>
              <KV k="query">
                {isTextQuery ? (
                  <span
                    onClick={() => onQueryClick?.(search.query.text)}
                    title="filter feed to this query"
                    style={{
                      fontFamily: MONO, color: "#f0f0f5", fontSize: 12,
                      cursor: "pointer",
                      textDecoration: "underline",
                      textDecorationColor: "rgba(255,255,255,0.2)",
                      textUnderlineOffset: 2,
                    }}
                  >{queryToString(search, trackById)}</span>
                ) : (
                  <span style={{ fontFamily: MONO, color: "#f0f0f5", fontSize: 12 }}>
                    {queryToString(search, trackById)}
                  </span>
                )}
              </KV>
              {search.query?.enhanced_text && (
                <KV k="enhanced">
                  <span style={{ fontFamily: MONO, color: "#a78bfa", fontSize: 12, fontStyle: "italic" }}>
                    {`"${search.query.enhanced_text}"`}
                  </span>
                </KV>
              )}
              <KV k="params">
                <code style={{ fontFamily: MONO, color: "#a0a0b0", fontSize: 11 }}>
                  {JSON.stringify(search.params || {})}
                </code>
              </KV>
              <KV k="versions">
                <span style={{ fontSize: 11 }}>
                  <Chip>{search.versions?.model || "—"}</Chip>{" "}
                  <Chip>idx {search.versions?.index || "—"}</Chip>{" "}
                  <Chip>git {(search.versions?.git_sha || "").slice(0, 7) || "—"}</Chip>
                </span>
              </KV>
              <KV k="session">
                <span style={{ fontFamily: MONO, color: "#7a7a8a", fontSize: 11 }}>
                  {label.session_id.length > 12
                    ? `${label.session_id.slice(0, 8)}…${label.session_id.slice(-4)}`
                    : label.session_id}
                </span>
              </KV>
            </>
          ) : (
            <div style={{ fontSize: 11, color: "#7a7a8a", fontStyle: "italic", padding: "8px 0" }}>
              Search context not loaded (outside filter window).
            </div>
          )}
        </div>
      </Section>

      <Section title={`Ranked results (${search?.results?.length || 0})`}
               subtitle={`Labels on this search: ${siblingLabels.length}`}>
        <RankList search={search} labelsByRank={labelsByRank}
                  focusTrackId={label.track_id} trackById={trackById} />
      </Section>
    </div>
  );
}
