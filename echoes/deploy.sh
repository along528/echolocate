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

# Deploy to Cloud Run. Public+CORS, IAP-protected at the domain layer (see setup_iap.sh).
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
if gcloud beta run domain-mappings describe \
        --domain="${DOMAIN}" --region=${REGION} --project="${PROJECT_ID}" &>/dev/null; then
    echo "Domain mapping already exists for ${DOMAIN}"
else
    echo "Creating domain mapping ${DOMAIN} -> ${SERVICE_NAME}..."
    gcloud beta run domain-mappings create \
        --service=${SERVICE_NAME} \
        --domain="${DOMAIN}" \
        --region=${REGION} \
        --project="${PROJECT_ID}"
    echo "Run \`gcloud beta run domain-mappings describe --domain=${DOMAIN} --region=${REGION}\` for DNS records."
fi

echo "Echoes deployed!"
echo "URL: https://${DOMAIN}/   (also reachable at the raw Cloud Run URL)"
echo ""
echo "Next steps if this is a first-time deploy:"
echo "  1. Add the DNS record shown by domain-mappings describe."
echo "  2. Add IAP on ${SERVICE_NAME} (mirror setup_iap.sh steps for cloud-crate-frontend)."
echo "  3. Add https://${DOMAIN} to vector-rs CORS_ALLOW_ORIGINS:"
echo "     gcloud run services update cloud-crate-vector-rs --region=${REGION} \\"
echo "         --update-env-vars CORS_ALLOW_ORIGINS=https://echolocate.app,https://${DOMAIN}"
