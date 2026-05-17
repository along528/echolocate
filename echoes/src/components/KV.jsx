export default function KV({ k, children }) {
  return (
    <div style={{
      display: "grid", gridTemplateColumns: "100px 1fr",
      gap: 12, padding: "5px 0",
      borderBottom: "1px dotted rgba(255,255,255,0.03)",
      alignItems: "center",
    }}>
      <div style={{
        fontSize: 10, textTransform: "uppercase", letterSpacing: 0.6,
        color: "#5a5a6c",
        fontFamily: "ui-monospace, SF Mono, Menlo, monospace",
      }}>{k}</div>
      <div style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis" }}>{children}</div>
    </div>
  );
}
