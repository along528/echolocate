// Vector-rs base URL.
// - Production: baked at build time via VITE_VECTOR_API_URL (set in deploy.sh /
//   cloudbuild.yaml; injected via Docker build arg).
// - Dev: defaults to localhost:8080 when the page is served from localhost.
// - Misconfigured prod (env var unset, hostname != localhost) fails loudly on
//   first call rather than silently pointing at the wrong host.
const ENV_BASE = import.meta.env.VITE_VECTOR_API_URL;
const ON_LOCALHOST =
  typeof window !== "undefined" &&
  (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1");
const BASE = ENV_BASE || (ON_LOCALHOST ? "http://localhost:8080" : null);

function requireBase() {
  if (!BASE) {
    throw new Error(
      "Echoes: VITE_VECTOR_API_URL is not set. Production builds must pass it as a Docker build arg (see echoes/deploy.sh).",
    );
  }
  return BASE;
}

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
  return jsonFetch(`${requireBase()}/labels/events${qs}`);
}

// POST /tracks/by-ids — batch metadata lookup, chunked at 500.
export async function fetchTracks(ids, source = "fma") {
  if (!ids?.length) return [];
  const base = requireBase();
  const chunks = [];
  for (let i = 0; i < ids.length; i += 500) chunks.push(ids.slice(i, i + 500));
  const results = await Promise.all(
    chunks.map((chunk) =>
      jsonFetch(`${base}/tracks/by-ids`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids: chunk, source }),
      }),
    ),
  );
  return results.flat();
}
