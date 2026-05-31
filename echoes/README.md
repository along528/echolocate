# Echoes — feedback review (Inspector)

Internal eval-team UI for browsing EchoLocate `SearchEvent` / `LabelEvent` records.
Reads from `vector-rs` (`GET /labels/events`, `POST /tracks/by-ids`).

- **Stack:** React + Vite static build, served by nginx on Cloud Run.
- **URL (production):** `https://echoes.echolocate.app/`
- **Service:** `cloud-crate-echoes` (independent of `cloud-crate-frontend`)
- **Design tokens:** `src/styles/tokens.css` (verbatim from the EchoLocate design system).

---

## Local development

```bash
# Terminal 1 — vector-rs (needs libduckdb + libonnxruntime locally)
cd ../vector-rs && INDEX_DB_PATH=../data/index.duckdb cargo run

# Terminal 2 — echoes dev server (Vite on :5173, talks to localhost:8080)
./start_local.sh
```

If you don't have `libonnxruntime` installed locally, you can drive the UI against
a tiny mock server — see the `/tmp/echoes_mock.py` example used during initial
development, or point `VITE_VECTOR_API_URL` at the deployed vector-rs Cloud Run URL.

---

## Deploy

```bash
./deploy.sh
```

The script:
1. Submits the image to Cloud Build (`gcr.io/<project-id>/cloud-crate-echoes`).
2. Deploys the new revision to Cloud Run (`cloud-crate-echoes`, region `us-central1`).
3. Creates the Cloud Run **domain mapping** for `echoes.echolocate.app` (idempotent — skips if already mapped).
4. Prints the **DNS records** GCP expects at your registrar and checks whether DNS currently resolves.

After a successful deploy you should see:

```
==========================================================
DNS records required at your registrar for echoes.echolocate.app:
==========================================================
  CNAME  echoes  ghs.googlehosted.com.
...
DNS resolves: echoes.echolocate.app -> ghs.googlehosted.com.
Echoes deployed: https://echoes.echolocate.app/
```

### First-time-only setup

The `deploy.sh` script handles everything Google-side, but a few steps are out of its reach:

**1. Add the DNS record at your registrar.**
The script prints the exact records (type + name + rrdata). For `echoes.echolocate.app` that's typically:

| Type | Name   | Value                  |
|------|--------|------------------------|
| CNAME | `echoes` | `ghs.googlehosted.com.` |

Cert provisioning won't begin until DNS resolves.

**2. (Optional) Gate with IAP.**
The public app at `echolocate.app` is IAP-protected via `setup_iap.sh`. The Echoes
service isn't, by default. To gate it the same way, run the equivalent block from
`setup_iap.sh` against `cloud-crate-echoes`:

```bash
PROJECT_ID="<your-gcp-project-id>"
REGION="us-central1"
SERVICE="cloud-crate-echoes"
USER_EMAIL="your-email@example.com"

PROJECT_NUMBER=$(gcloud projects describe ${PROJECT_ID} --format='value(projectNumber)')
IAP_SA="service-${PROJECT_NUMBER}@gcp-sa-iap.iam.gserviceaccount.com"

# Grant IAP service agent invoker on the service
gcloud run services add-iam-policy-binding ${SERVICE} \
    --region=${REGION} \
    --member="serviceAccount:${IAP_SA}" \
    --role=roles/run.invoker --project=${PROJECT_ID}

# Configure the OAuth client (reuse the one from setup_iap.sh)
IAP_CLIENT_SECRET=$(gcloud secrets versions access latest \
    --secret=iap-client-secret --project=${PROJECT_ID})
gcloud beta iap settings set /dev/stdin \
    --project=${PROJECT_ID} \
    --resource-type=cloud-run \
    --service=${SERVICE} \
    --region=${REGION} <<EOF
accessSettings:
  oauthSettings:
    clientId: "<oauth-client-id>"
    clientSecret: "${IAP_CLIENT_SECRET}"
EOF

# Grant a user access
gcloud beta iap web add-iam-policy-binding \
    --resource-type=cloud-run --service=${SERVICE} --region=${REGION} \
    --member="user:${USER_EMAIL}" \
    --role="roles/iap.httpsResourceAccessor" --project=${PROJECT_ID}

# Turn IAP on for the service
gcloud beta run services update ${SERVICE} --region=${REGION} --iap
```

**3. Re-deploy vector-rs so it allows the new origin.**
`vector-rs/deploy.sh` is already configured with both origins in `CORS_ALLOW_ORIGINS`;
it just needs a redeploy to pick up the env-var change:

```bash
cd ../vector-rs && ./deploy.sh
```

(`CORS_ALLOW_ORIGINS=https://echolocate.app,https://echoes.echolocate.app`)

---

## Verifying production

```bash
# Service reachable (200 if no IAP, 302 if IAP-gated)
curl -sI https://echoes.echolocate.app/ | head -1

# Read API directly (CORS won't apply to curl)
curl -s "${VECTOR_API_URL}/labels/events?limit=3" | python3 -m json.tool | head

# In the browser: open the URL, click a feed row, confirm the detail panel
# populates and the ranked-results list scrolls the focused row into view.
```

---

## Rollback

Cloud Run keeps prior revisions. To roll back:

```bash
gcloud run services update-traffic cloud-crate-echoes \
    --region=us-central1 \
    --to-revisions=cloud-crate-echoes-<PRIOR_REVISION>=100
```

`gcloud run revisions list --service=cloud-crate-echoes --region=us-central1` shows the candidates.
