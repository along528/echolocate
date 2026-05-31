export default function VolumeSpark({ days, byDay, width = 220, height = 36, color = "#6366f1", showFill = true }) {
  const PAD = 2;
  const counts = days.map((d) => (byDay[d] || []).length);
  const max = Math.max(1, ...counts);
  const innerW = width - PAD * 2;
  const innerH = height - PAD * 2;
  const xOf = (i) => PAD + (i / Math.max(1, counts.length - 1)) * innerW;
  const yOf = (v) => PAD + innerH - (v / max) * innerH;
  const pts = counts.map((v, i) => `${xOf(i)},${yOf(v)}`).join(" ");
  const area = `${PAD},${PAD + innerH} ${pts} ${PAD + innerW},${PAD + innerH}`;
  return (
    <svg width={width} height={height} style={{ display: "block" }}>
      {showFill && <polygon points={area} fill={color} opacity="0.18" />}
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.5" />
    </svg>
  );
}
