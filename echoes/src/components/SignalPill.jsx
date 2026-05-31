import { SIGNAL_META } from "../lib/signals.js";

export default function SignalPill({ signal, size = "sm" }) {
  const m = SIGNAL_META[signal] || SIGNAL_META.cleared;
  const pad = size === "xs" ? "0 5px" : size === "lg" ? "3px 10px" : "1px 7px";
  const fs = size === "xs" ? 10 : size === "lg" ? 13 : 11;
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 4,
      padding: pad, borderRadius: 4,
      background: m.bg, color: m.color,
      fontSize: fs, fontWeight: 600,
      letterSpacing: 0.3, textTransform: "lowercase",
      whiteSpace: "nowrap",
    }}>
      <span style={{ fontFamily: "ui-monospace, SF Mono, Menlo, monospace", lineHeight: 1 }}>{m.glyph}</span>
      <span>{m.label}</span>
    </span>
  );
}
