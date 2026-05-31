export default function Stat({ label, value, sub, accent = "#f0f0f5" }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
      <div style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: 0.6, color: "#7a7a8a" }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 600, color: accent, fontVariantNumeric: "tabular-nums", lineHeight: 1.1 }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: "#7a7a8a", fontVariantNumeric: "tabular-nums" }}>{sub}</div>}
    </div>
  );
}
