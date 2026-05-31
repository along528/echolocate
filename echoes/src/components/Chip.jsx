const TONES = {
  muted:  { bg: "rgba(255,255,255,0.04)", color: "#a0a0b0", border: "rgba(255,255,255,0.08)" },
  indigo: { bg: "rgba(99,102,241,0.12)",  color: "#a5a8ff", border: "rgba(99,102,241,0.28)" },
  amber:  { bg: "rgba(234,179,8,0.10)",   color: "#eab308", border: "rgba(234,179,8,0.30)" },
  danger: { bg: "rgba(176,69,69,0.14)",   color: "#e08a8a", border: "rgba(176,69,69,0.30)" },
};

export default function Chip({ children, tone = "muted" }) {
  const t = TONES[tone] || TONES.muted;
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", padding: "1px 7px",
      borderRadius: 4, background: t.bg, color: t.color,
      border: `1px solid ${t.border}`,
      fontSize: 10, letterSpacing: 0.4, textTransform: "uppercase",
      fontFamily: "ui-monospace, SF Mono, Menlo, monospace",
      fontWeight: 500, whiteSpace: "nowrap",
    }}>{children}</span>
  );
}
