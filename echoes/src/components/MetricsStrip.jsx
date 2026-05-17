import { useMemo } from "react";
import { SIGNAL_META, SIGNAL_ORDER } from "../lib/signals.js";
import { bucketByDay, dayRange, precisionBands } from "../lib/aggregate.js";
import StackedSignalChart from "./charts/StackedSignalChart.jsx";
import PrecisionAtRank from "./charts/PrecisionAtRank.jsx";
import VolumeSpark from "./charts/VolumeSpark.jsx";

const MONO = "ui-monospace, SF Mono, Menlo, monospace";

function pctColor(pct) {
  if (pct == null) return "#5a5a6c";
  if (pct >= 60) return "#2e8b57";
  if (pct >= 30) return "#c79a2c";
  return "#b04545";
}

export default function MetricsStrip({ labels, searches, open, onToggle }) {
  const days = useMemo(() => {
    if (!searches.length && !labels.length) return [];
    const all = [...searches, ...labels].map((e) => e.timestamp).sort();
    return dayRange(all[0], all[all.length - 1]);
  }, [searches, labels]);

  const labelsByDay = useMemo(() => bucketByDay(labels), [labels]);
  const searchesByDay = useMemo(() => bucketByDay(searches), [searches]);
  const bands = useMemo(() => precisionBands(labels), [labels]);

  return (
    <div style={{
      borderBottom: "1px solid rgba(255,255,255,0.08)",
      background: "#0c0c14",
      flexShrink: 0,
    }}>
      <div onClick={onToggle} style={{
        display: "flex", alignItems: "center", gap: 8,
        padding: "6px 14px", cursor: "pointer",
        borderBottom: open ? "1px solid rgba(255,255,255,0.04)" : "none",
        userSelect: "none",
      }}>
        <span style={{ color: "#5a5a6c", fontFamily: MONO, fontSize: 11, width: 10 }}>
          {open ? "▾" : "▸"}
        </span>
        <span style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: 0.6, color: "#a0a0b0", fontWeight: 600 }}>
          Metrics
        </span>
        <span style={{ flex: 1 }} />
        <span style={{ display: "flex", gap: 14, fontSize: 11, color: "#7a7a8a", fontVariantNumeric: "tabular-nums" }}>
          {bands.map((b) => (
            <span key={b.label}>
              <span style={{ color: "#5a5a6c", letterSpacing: 0.4, textTransform: "uppercase", fontSize: 10, marginRight: 5 }}>
                P@{b.label}
              </span>
              <span style={{ color: pctColor(b.pct), fontWeight: 700 }}>
                {b.pct == null ? "—" : `${b.pct}%`}
              </span>
              <span style={{ color: "#5a5a6c", marginLeft: 4 }}>({b.tot})</span>
            </span>
          ))}
        </span>
      </div>
      {open && (
        <div style={{
          display: "grid",
          gridTemplateColumns: "1.4fr 1fr 1fr",
          padding: "10px 14px 12px",
          gap: 14,
        }}>
          <Card title="Signal mix over time" subtitle={`${labels.length} labels`}>
            <StackedSignalChart days={days} byDay={labelsByDay} width={520} height={120} showAxis />
            <MiniLegend />
          </Card>
          <Card title="Precision at rank" subtitle="share of signals per rank">
            <PrecisionAtRank labels={labels} width={300} height={120} bins={10} />
            <MiniLegend />
          </Card>
          <Card title="Volume" subtitle="searches and labels per day">
            <VolumeMini days={days} searchesByDay={searchesByDay} labelsByDay={labelsByDay} />
          </Card>
        </div>
      )}
    </div>
  );
}

function Card({ title, subtitle, children }) {
  return (
    <div style={{ minWidth: 0 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 6 }}>
        <span style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: 0.6, color: "#a0a0b0", fontWeight: 600 }}>
          {title}
        </span>
        {subtitle && <span style={{ fontSize: 10, color: "#5a5a6c" }}>{subtitle}</span>}
      </div>
      {children}
    </div>
  );
}

function MiniLegend() {
  return (
    <div style={{ display: "flex", gap: 10, marginTop: 4 }}>
      {SIGNAL_ORDER.map((s) => {
        const m = SIGNAL_META[s];
        return (
          <span key={s} style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 9, color: "#7a7a8a" }}>
            <span style={{ width: 7, height: 7, background: m.color, borderRadius: 1, opacity: s === "cleared" ? 0.5 : 1 }} />
            {s}
          </span>
        );
      })}
    </div>
  );
}

function VolumeMini({ days, searchesByDay, labelsByDay }) {
  const sCounts = days.map((d) => (searchesByDay[d] || []).length);
  const lCounts = days.map((d) => (labelsByDay[d] || []).length);
  const sTot = sCounts.reduce((a, b) => a + b, 0);
  const lTot = lCounts.reduce((a, b) => a + b, 0);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <RowMetric label="searches" total={sTot} days={days} byDay={searchesByDay} color="#a78bfa" />
      <RowMetric label="labels"   total={lTot} days={days} byDay={labelsByDay}   color="#6366f1" />
      <div style={{
        fontSize: 10, color: "#5a5a6c", marginTop: 2,
        fontVariantNumeric: "tabular-nums", letterSpacing: 0.3,
      }}>
        {sTot ? (lTot / sTot).toFixed(2) : "0"} labels per search · {days.length} days
      </div>
    </div>
  );
}

function RowMetric({ label, total, days, byDay, color }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "60px 60px 1fr", alignItems: "center", gap: 8 }}>
      <span style={{ fontSize: 10, color: "#7a7a8a", textTransform: "uppercase", letterSpacing: 0.5 }}>{label}</span>
      <span style={{ fontSize: 14, fontWeight: 600, color: "#f0f0f5", fontVariantNumeric: "tabular-nums" }}>
        {total.toLocaleString()}
      </span>
      <VolumeSpark days={days} byDay={byDay} width={180} height={28} color={color} showFill />
    </div>
  );
}
