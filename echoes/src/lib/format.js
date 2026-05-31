export function fmtClockTime(iso) {
  const d = new Date(iso);
  return d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false });
}

export function fmtDateTime(iso) {
  const d = new Date(iso);
  const day = d.toLocaleDateString("en-US", { month: "short", day: "2-digit" });
  return `${day} ${fmtClockTime(iso)}`;
}

export function fmtDay(iso) {
  const d = new Date(iso);
  return d.toLocaleDateString("en-US", { month: "short", day: "2-digit" });
}

export function fmtRelative(iso, now) {
  const t = new Date(iso).getTime();
  const dt = now - t;
  if (dt < 60_000) return `${Math.max(1, Math.floor(dt / 1000))}s ago`;
  if (dt < 3_600_000) return `${Math.floor(dt / 60_000)}m ago`;
  if (dt < 86_400_000) return `${Math.floor(dt / 3_600_000)}h ago`;
  return `${Math.floor(dt / 86_400_000)}d ago`;
}

export const fmtDayKey = (iso) => iso.slice(0, 10);
