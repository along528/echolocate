// Format a parent search's query as a one-liner for feed/detail sublines.
// `trackById` is the in-memory track-cache map; missing entries fall back to ids.
export function queryToString(search, trackById = {}) {
  if (!search) return "—";
  const q = search.query || {};
  const k = search.query_kind;
  const params = search.params || {};
  if (k === "text") return `"${q.text ?? ""}"`;
  if (k === "seed") {
    const id = q.seed_track_id;
    const tr = trackById[id];
    const lbl = tr ? `${tr.artist} — ${tr.title}` : id;
    return `${params.polarity === "dissimilar" ? "≠" : "≈"} ${lbl}`;
  }
  if (k === "pair") {
    const [a, b] = q.pair_track_ids || [];
    const ta = trackById[a];
    const tb = trackById[b];
    return `${ta ? ta.title : a} ⇄ ${tb ? tb.title : b}`;
  }
  return "—";
}
