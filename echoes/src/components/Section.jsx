export default function Section({ title, subtitle, children }) {
  return (
    <div style={{ borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
      <div style={{
        padding: "12px 20px 4px", display: "flex",
        alignItems: "baseline", gap: 10,
      }}>
        <div style={{
          fontSize: 10, textTransform: "uppercase", letterSpacing: 0.6,
          color: "#a0a0b0", fontWeight: 600,
        }}>{title}</div>
        {subtitle && <div style={{ fontSize: 11, color: "#5a5a6c" }}>{subtitle}</div>}
      </div>
      {children}
    </div>
  );
}
