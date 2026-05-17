import Stat from "./Stat.jsx";

export default function Header({ stats }) {
  return (
    <div style={{
      display: "flex", alignItems: "center",
      padding: "10px 16px", gap: 24,
      background: "#12121a",
      borderBottom: "1px solid rgba(255,255,255,0.08)",
    }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
        <span style={{
          fontSize: 18, fontWeight: 700, letterSpacing: "-0.01em",
          background: "linear-gradient(135deg, #6366f1, #8b5cf6)",
          WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent",
        }}>Echoes</span>
        <span style={{ fontSize: 11, color: "#7a7a8a", letterSpacing: 0.4, textTransform: "uppercase" }}>
          feedback review · inspector
        </span>
      </div>
      <div style={{ flex: 1 }} />
      <div style={{ display: "flex", gap: 28 }}>
        <Stat label="Searches" value={stats.searches.toLocaleString()} />
        <Stat label="Labels" value={stats.labels.toLocaleString()} sub={`${stats.perSearch} per search`} />
        <Stat label="Relevant" value={`${stats.relRate}%`} accent="#2e8b57"
              sub={`${stats.c.relevant.toLocaleString()} signals`} />
        <Stat label="Negative" value={`${stats.negRate}%`} accent="#c79a2c"
              sub={`${(stats.c.wrong + stats.c.borderline).toLocaleString()} signals`} />
        <Stat label="Note Cov." value={`${stats.noteRate}%`}
              sub={`${stats.noted} of ${stats.c.borderline + stats.c.wrong}`} />
      </div>
    </div>
  );
}
