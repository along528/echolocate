# Sonar — EchoLocate map frontend

Standalone React + Vite implementation of the "sonar map + list" redesign,
deployed as its own Cloud Run service (`cloud-crate-sonar`) at **sonar.echolocate.app**
(Cloud Run domain mapping, mirroring the `echoes/` service), separate from the legacy
`frontend/`.

## Local development
```bash
cd sonar
npm install
VITE_VECTOR_API_URL=https://cloud-crate-vector-rs-xxxx.run.app npm run dev
# open http://localhost:5180
```
`VITE_VECTOR_API_URL` points at the vector service. Find it with:
```bash
gcloud run services describe cloud-crate-vector-rs --region us-central1 --format='value(status.url)'
```
The vector service's `CORS_ALLOW_ORIGINS` must include the origin you load this from
(e.g. `http://localhost:5180` for dev, and the deployed sonar URL for prod).

## Deploy
```bash
./deploy.sh   # discovers the vector-rs URL automatically; or set VECTOR_API_URL=...
```
Builds via `cloudbuild.yaml` (bakes `VITE_VECTOR_API_URL`), deploys to Cloud Run, and
creates/repeats the `sonar.echolocate.app` domain mapping (prints the DNS record to add).
On first deploy, re-deploy `vector-rs` so CORS allows `https://sonar.echolocate.app`
(already in `vector-rs/deploy.sh`).

## Firestore cache (optional warm-up)
Sonar reads two Firestore caches (project `cloud-crate-485418`), like the legacy
frontend — both are read-only from the browser and degrade gracefully:
- `semantic_search_cache` — pre-computed `/semantic-search` results (cache miss
  just falls through to a live request).
- `sonar_config/suggestions` — the suggested-chip list (falls back to the baked-in
  `src/suggested_chips.json` when absent).

To warm them, run the populate script (needs app-default credentials):
```bash
gcloud auth application-default login
pip install requests google-cloud-firestore
python populate_cache.py                     # warm cache for every chip (limit=24, enhance=true)
python populate_cache.py --write-suggestions # also publish the chip list to Firestore
python populate_cache.py --dry-run           # preview keys without calling anything
```
Cache keys must match the frontend's request params (`source=fma`, `limit=24`,
`enhance=true`) and the chip labels — the script uses those by default and reads
the same `src/suggested_chips.json` the app bundles, so keys line up.

## Layout
- `src/Sonar.jsx` — the component (tagger, view toggle, playlist rail, map/list, now-playing)
- `src/svg-bits.jsx` — Wordmark / Waveform (seekable) / DistanceChip
- `src/icons.jsx` — track-action icons ported from the legacy frontend
- `src/api.js` — vector-service client (+ `mapBackdrop`, Firestore search cache)
- `src/cache.js` — Firestore client (search cache + suggested chips)
- `src/labels.js` — search/label logging (training signal)
- `src/suggested_chips.json` — chip vocabulary, shared with `populate_cache.py`
- `src/style.css`, `src/sonar.css`, `src/design/*` — component styles (ported from the prototype kit)

See `TODO.md` for intentionally deferred features.
