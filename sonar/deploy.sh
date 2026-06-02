#!/bin/bash
set -e
cd "$(dirname "$0")"

PROJECT_ID="cloud-crate-485418"
REGION="us-central1"
SERVICE_NAME="cloud-crate-sonar"
DOMAIN="sonar.echolocate.app"
IMAGE="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"

# Vector-rs base URL — baked into the bundle at build time. By default we discover
# the URL from Cloud Run; override by exporting VECTOR_API_URL before running.
if [ -z "${VECTOR_API_URL:-}" ]; then
    VECTOR_API_URL=$(gcloud run services describe cloud-crate-vector-rs \
        --region="${REGION}" --project="${PROJECT_ID}" --format='value(status.url)')
fi
if [ -z "${VECTOR_API_URL}" ]; then
    echo "ERROR: could not determine vector-rs URL. Set VECTOR_API_URL=... and re-run." >&2
    exit 1
fi

echo "Building and deploying Sonar..."
echo "  Baking VITE_VECTOR_API_URL=${VECTOR_API_URL}"

# Build + push via cloudbuild.yaml so we can pass VITE_VECTOR_API_URL as a build arg.
gcloud builds submit \
    --config cloudbuild.yaml \
    --substitutions "_IMAGE=${IMAGE},_VITE_VECTOR_API_URL=${VECTOR_API_URL}" \
    --project="${PROJECT_ID}"

# Deploy to Cloud Run.
gcloud beta run deploy ${SERVICE_NAME} \
    --image "${IMAGE}" \
    --platform managed \
    --region ${REGION} \
    --allow-unauthenticated \
    --no-iap \
    --ingress all \
    --port 8080 \
    --project="${PROJECT_ID}"

# Cloud Run domain mapping. Idempotent — only creates if not already mapped.
NEW_MAPPING=false
if gcloud beta run domain-mappings describe \
        --domain="${DOMAIN}" --region=${REGION} --project="${PROJECT_ID}" &>/dev/null; then
    echo "Domain mapping already exists for ${DOMAIN}."
else
    echo "Creating domain mapping ${DOMAIN} -> ${SERVICE_NAME}..."
    gcloud beta run domain-mappings create \
        --service=${SERVICE_NAME} \
        --domain="${DOMAIN}" \
        --region=${REGION} \
        --project="${PROJECT_ID}"
    NEW_MAPPING=true
fi

# Surface the required DNS records every time, so the registrar config can be verified.
echo ""
echo "=========================================================="
echo "DNS records required at your registrar for ${DOMAIN}:"
echo "=========================================================="
gcloud beta run domain-mappings describe \
    --domain="${DOMAIN}" --region=${REGION} --project="${PROJECT_ID}" \
    --format='table[no-heading,box](status.resourceRecords[].type,status.resourceRecords[].name,status.resourceRecords[].rrdata)' \
    || true
echo ""

# Light propagation check — non-blocking, informational.
LOOKUP="$(dig +short "${DOMAIN}" CNAME 2>/dev/null | head -1)"
if [ -z "$LOOKUP" ]; then
    LOOKUP="$(dig +short "${DOMAIN}" A 2>/dev/null | head -1)"
fi
if [ -n "$LOOKUP" ]; then
    echo "DNS resolves: ${DOMAIN} -> ${LOOKUP}"
else
    echo "DNS not yet propagated for ${DOMAIN}. Add the record above; re-check with:"
    echo "  dig +short ${DOMAIN} CNAME"
fi

echo ""
echo "Sonar deployed: https://${DOMAIN}/"
echo ""

if [ "$NEW_MAPPING" = true ]; then
    cat <<MSG
First-time deploy reminders:
  1. Add the DNS record above at your registrar. Cert provisioning starts once DNS resolves.
  2. Re-deploy vector-rs so CORS_ALLOW_ORIGINS includes https://${DOMAIN}:
       cd ../vector-rs && ./deploy.sh
     (the CORS list is already updated in vector-rs/deploy.sh — just needs to re-deploy.)
MSG
fi
