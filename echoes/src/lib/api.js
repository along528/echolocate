// Production: served at echolocate.app/echoes, vector-rs is the deployed Cloud Run URL.
// Dev: defaults to localhost:8080 (vector-rs default port).
const BASE =
  import.meta.env.VITE_VECTOR_API_URL ||
  (typeof window !== "undefined" &&
    (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1")
      ? "http://localhost:8080"
      : "https://cloud-crate-vector-rs-403961692263.us-central1.run.app");

async function jsonFetch(url, init) {
  const r = await fetch(url, init);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

function buildQuery(params) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) {
      if (v.length) q.set(k, v.join(","));
    } else {
      q.set(k, String(v));
    }
  }
  const s = q.toString();
  return s ? `?${s}` : "";
}

// GET /labels/events — paginated read.
// Returns { events: [{type, ...}], next_cursor }
export async function fetchEvents({ from, to, endpoint, model, index, signals, cursor, limit = 500 } = {}) {
  const qs = buildQuery({ from, to, endpoint, model, index, signals, cursor, limit });
  return jsonFetch(`${BASE}/labels/events${qs}`);
}

// GET /labels/events?since=…
export async function fetchSince(sinceIso, limit = 500) {
  const qs = buildQuery({ since: sinceIso, limit });
  return jsonFetch(`${BASE}/labels/events${qs}`);
}

// POST /tracks/by-ids — batch metadata lookup, chunked at 500.
export async function fetchTracks(ids, source = "fma") {
  if (!ids?.length) return [];
  const chunks = [];
  for (let i = 0; i < ids.length; i += 500) chunks.push(ids.slice(i, i + 500));
  const results = await Promise.all(
    chunks.map((chunk) =>
      jsonFetch(`${BASE}/tracks/by-ids`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids: chunk, source }),
      }),
    ),
  );
  return results.flat();
}
