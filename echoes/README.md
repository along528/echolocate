# Echoes — feedback review (Inspector)

Internal eval-team UI for browsing EchoLocate `SearchEvent` / `LabelEvent` records.
Reads from vector-rs (`GET /labels/events`, `POST /tracks/by-ids`).

## Local

```bash
# Terminal 1: vector-rs
cd ../vector-rs && INDEX_DB_PATH=../data/index.duckdb cargo run

# Terminal 2: echoes
./start_local.sh           # http://localhost:5173, talks to localhost:8080
```

## Deploy

```bash
./deploy.sh                # builds image, deploys cloud-crate-echoes,
                           # maps echoes.echolocate.app to it
```

First-time deploy reminders printed at the end of `./deploy.sh`:
1. Add the DNS record for `echoes.echolocate.app` (see `gcloud beta run domain-mappings describe`).
2. Mirror IAP setup from `setup_iap.sh` against `cloud-crate-echoes` if you want it gated.
3. Update vector-rs `CORS_ALLOW_ORIGINS` to include `https://echoes.echolocate.app`.

## Stack

React + Vite static build, served by nginx on Cloud Run. Design tokens live in
`src/styles/tokens.css` (verbatim from the EchoLocate design system).
