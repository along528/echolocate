import { fmtDayKey } from "./format.js";

export function bucketByDay(events) {
  const map = {};
  for (const e of events) {
    const k = fmtDayKey(e.timestamp);
    if (!map[k]) map[k] = [];
    map[k].push(e);
  }
  return map;
}

export function dayRange(startIso, endIso) {
  if (!startIso || !endIso) return [];
  const out = [];
  const s = new Date(startIso.slice(0, 10) + "T00:00:00Z").getTime();
  const e = new Date(endIso.slice(0, 10) + "T00:00:00Z").getTime();
  for (let t = s; t <= e; t += 86_400_000) {
    out.push(new Date(t).toISOString().slice(0, 10));
  }
  return out;
}

// Per-band rollups for the metrics-strip header: P@top-3, P@4–10, P@11+
const BANDS = [
  { label: "top 3", lo: 0, hi: 2 },
  { label: "4–10", lo: 3, hi: 9 },
  { label: "11+",  lo: 10, hi: Infinity },
];

export function precisionBands(labels) {
  return BANDS.map((b) => {
    let rel = 0, tot = 0;
    for (const l of labels) {
      if (l.signal === "cleared" || l.rank < 0) continue;
      if (l.rank >= b.lo && l.rank <= b.hi) {
        tot++;
        if (l.signal === "relevant") rel++;
      }
    }
    return { ...b, rel, tot, pct: tot ? Math.round((rel / tot) * 100) : null };
  });
}

// Header summary stats — searches/labels totals, relevant/negative rates, note coverage.
export function computeStats(labels, searches) {
  const c = { relevant: 0, borderline: 0, wrong: 0, cleared: 0 };
  for (const l of labels) c[l.signal]++;
  const total = labels.length;
  const noted = labels.filter((l) => l.note).length;
  const neg = c.borderline + c.wrong;
  return {
    searches: searches.length,
    labels: total,
    perSearch: searches.length ? (total / searches.length).toFixed(2) : "0",
    relRate: total ? Math.round((c.relevant / total) * 100) : 0,
    negRate: total ? Math.round((neg / total) * 100) : 0,
    noted,
    noteRate: neg ? Math.round((noted / neg) * 100) : 0,
    c,
  };
}
