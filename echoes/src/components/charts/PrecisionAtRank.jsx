import { SIGNAL_META } from "../../lib/signals.js";

const MONO = "ui-monospace, SF Mono, Menlo, monospace";

export default function PrecisionAtRank({ labels, bins = 10, width = 360, height = 140 }) {
  const PAD = { t: 8, r: 8, b: 22, l: 28 };
  const innerW = width - PAD.l - PAD.r;
  const innerH = height - PAD.t - PAD.b;

  const buckets = Array.from({ length: bins }, () => ({ relevant: 0, borderline: 0, wrong: 0, total: 0 }));
  for (const l of labels) {
    if (l.signal === "cleared") continue;
    if (l.rank < 0) continue;
    const idx = Math.min(bins - 1, l.rank);
    buckets[idx][l.signal] = (buckets[idx][l.signal] || 0) + 1;
    buckets[idx].total += 1;
  }
  const barW = innerW / bins;

  return (
    <svg width={width} height={height} style={{ display: "block" }}>
      {[0, 0.25, 0.5, 0.75, 1].map((f) => (
        <line key={f} x1={PAD.l} x2={PAD.l + innerW}
              y1={PAD.t + innerH - innerH * f} y2={PAD.t + innerH - innerH * f}
              stroke="rgba(255,255,255,0.05)" />
      ))}
      {["0", "25", "50", "75", "100"].map((s, i) => (
        <text key={s} x={PAD.l - 6} y={PAD.t + innerH - innerH * (i / 4) + 3}
              fill="#6f6f80" fontSize="9" textAnchor="end" fontFamily={MONO}>{s}</text>
      ))}
      {buckets.map((b, i) => {
        if (b.total === 0) {
          return (
            <text key={i} x={PAD.l + i * barW + barW / 2} y={PAD.t + innerH + 12}
                  fill="#6f6f80" fontSize="9" textAnchor="middle" fontFamily={MONO}>
              {i === bins - 1 ? `${i}+` : i}
            </text>
          );
        }
        const x = PAD.l + i * barW + 1;
        const w = barW - 2;
        let yCursor = PAD.t + innerH;
        const order = ["wrong", "borderline", "relevant"];
        return (
          <g key={i}>
            {order.map((sig) => {
              const v = (b[sig] || 0) / b.total;
              const h = v * innerH;
              yCursor -= h;
              return <rect key={sig} x={x} y={yCursor} width={w} height={h} fill={SIGNAL_META[sig].color} opacity="0.85" />;
            })}
            <text x={x + w / 2} y={PAD.t + innerH + 12} fill="#6f6f80" fontSize="9"
                  textAnchor="middle" fontFamily={MONO}>
              {i === bins - 1 ? `${i}+` : i}
            </text>
            <text x={x + w / 2} y={PAD.t - 2} fill="#5a5a6c" fontSize="8"
                  textAnchor="middle" fontFamily={MONO}>
              {b.total}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
