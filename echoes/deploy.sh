#!/bin/bash
set -e

cd "$(dirname "$0")"

PROJECT_ID="cloud-crate-485418"
REGION="us-central1"
SERVICE_NAME="cloud-crate-echoes"
DOMAIN="echoes.echolocate.app"
IMAGE="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"

echo "Building and deploying Echoes Inspector..."

# Build + push (echoes/ is the build context; echoes/.dockerignore skips node_modules + dist)
gcloud builds submit --tag "${IMAGE}" --project="${PROJECT_ID}"

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

# Surface the required DNS records every time, so the user can verify their
# registrar config matches what GCP expects.
echo ""
echo "=========================================================="
echo "DNS records required at your registrar for ${DOMAIN}:"
echo "=========================================================="
gcloud beta run domain-mappings describe \
    --domain="${DOMAIN}" --region=${REGION} --project="${PROJECT_ID}" \
    --format='table[no-heading,box](status.resourceRecords[].type,status.resourceRecords[].name,status.resourceRecords[].rrdata)' \
    || true
echo ""

# Light propagation check — non-blocking, just informational.
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
echo "Echoes deployed: https://${DOMAIN}/"
echo ""

if [ "$NEW_MAPPING" = true ]; then
    cat <<MSG
First-time deploy reminders:
  1. Add the DNS record above at your registrar. Cert provisioning starts once DNS resolves.
  2. (Optional) Gate the service with IAP — mirror setup_iap.sh against ${SERVICE_NAME}.
  3. Re-deploy vector-rs so CORS_ALLOW_ORIGINS includes https://${DOMAIN}:
       cd ../vector-rs && ./deploy.sh
     (the CORS list is already updated in vector-rs/deploy.sh — just needs to re-deploy.)
MSG
fi
