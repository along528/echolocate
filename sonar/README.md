# Sonar — EchoLocate Layout D frontend

Standalone React + Vite implementation of the "sonar map + list" redesign (Layout D),
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

## Layout
- `src/LayoutD.jsx` — the component (tagger, view toggle, trail rail, map/list, now-playing)
- `src/svg-bits.jsx` — Wordmark / Waveform / DistanceChip
- `src/api.js` — vector-service client (+ `mapBackdrop`)
- `src/labels.js` — search/label logging (training signal)
- `src/style.css`, `src/styles/*` , `src/design/*` — prototype styles (ported verbatim)

See `TODO.md` for intentionally deferred features.
