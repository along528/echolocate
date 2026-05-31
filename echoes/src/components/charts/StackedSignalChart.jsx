import { SIGNAL_META, SIGNAL_ORDER } from "../../lib/signals.js";

const MONO = "ui-monospace, SF Mono, Menlo, monospace";

export default function StackedSignalChart({ days, byDay, width = 600, height = 140, showAxis = true }) {
  const PAD = { t: 8, r: 8, b: showAxis ? 20 : 4, l: 28 };
  const innerW = width - PAD.l - PAD.r;
  const innerH = height - PAD.t - PAD.b;

  const series = days.map((d) => {
    const labs = byDay[d] || [];
    const c = { relevant: 0, borderline: 0, wrong: 0, cleared: 0 };
    for (const l of labs) c[l.signal] = (c[l.signal] || 0) + 1;
    return { day: d, total: labs.length, c };
  });
  const maxTotal = Math.max(8, ...series.map((s) => s.total));
  const xOf = (i) => PAD.l + (i / Math.max(1, days.length - 1)) * innerW;
  const yOf = (v) => PAD.t + innerH - (v / maxTotal) * innerH;

  const polys = [];
  let baseline = Array(days.length).fill(0);
  for (const sig of SIGNAL_ORDER) {
    const top = baseline.map((b, i) => b + (series[i].c[sig] || 0));
    const pts = [
      ...days.map((_, i) => `${xOf(i)},${yOf(baseline[i])}`),
      ...[...days].reverse().map((_, i) => {
        const ii = days.length - 1 - i;
        return `${xOf(ii)},${yOf(top[ii])}`;
      }),
    ].join(" ");
    polys.push({ sig, pts });
    baseline = top;
  }
  const topLine = days.map((_, i) => `${xOf(i)},${yOf(series[i].total)}`).join(" ");

  return (
    <svg width={width} height={height} style={{ display: "block" }}>
      {[0, 0.5, 1].map((f) => (
        <line key={f} x1={PAD.l} x2={PAD.l + innerW} y1={yOf(maxTotal * f)} y2={yOf(maxTotal * f)}
              stroke="rgba(255,255,255,0.05)" strokeWidth="1" />
      ))}
      <text x={PAD.l - 6} y={PAD.t + 8} fill="#6f6f80" fontSize="10" textAnchor="end" fontFamily={MONO}>{maxTotal}</text>
      <text x={PAD.l - 6} y={PAD.t + innerH + 3} fill="#6f6f80" fontSize="10" textAnchor="end" fontFamily={MONO}>0</text>
      {polys.map(({ sig, pts }) => (
        <polygon key={sig} points={pts} fill={SIGNAL_META[sig].color} opacity={sig === "cleared" ? 0.35 : 0.78} />
      ))}
      <polyline points={topLine} fill="none" stroke="rgba(240,240,245,0.5)" strokeWidth="1" />
      {showAxis && days.map((d, i) => {
        if (days.length > 10 && i % 2 !== 0 && i !== days.length - 1) return null;
        return (
          <text key={d} x={xOf(i)} y={height - 6} fill="#6f6f80" fontSize="10"
                textAnchor="middle" fontFamily={MONO}>
            {d.slice(5)}
          </text>
        );
      })}
    </svg>
  );
}
