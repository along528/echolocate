#!/bin/bash
set -e

# IAP + Domain Setup for Cloud Crate (no load balancer)
# - Grants IAP access on the frontend Cloud Run service
# - Grants MCP service account run.invoker on vector service
# - Creates Cloud Run domain mapping for echolocate.app

PROJECT_ID="cloud-crate-485418"
REGION="us-central1"
FRONTEND_SERVICE="cloud-crate-frontend"
VECTOR_SERVICE="cloud-crate-vector"
MCP_SERVICE="cloud-crate-mcp"
DOMAIN="echolocate.app"

USER_EMAIL="${1:-}"
if [ -z "$USER_EMAIL" ]; then
    echo "Usage: ./setup_iap.sh <your-google-email>"
    exit 1
fi

echo "Setting up IAP + domain mapping for Cloud Crate..."
echo "Authorized user: ${USER_EMAIL}"

# ============================================================
# 1. Grant IAP access on frontend Cloud Run service
# ============================================================
echo ""
echo "Granting IAP access to ${USER_EMAIL} on frontend..."

gcloud iap web add-iam-policy-binding \
    --resource-type=cloud-run \
    --service=${FRONTEND_SERVICE} \
    --region=${REGION} \
    --member="user:${USER_EMAIL}" \
    --role="roles/iap.httpsResourceAccessor" \
    --project=${PROJECT_ID}

# ============================================================
# 2. Grant MCP service account run.invoker on vector service
# ============================================================
echo ""
echo "Granting MCP service account access to vector service..."

MCP_SA=$(gcloud run services describe ${MCP_SERVICE} \
    --region=${REGION} \
    --project=${PROJECT_ID} \
    --format='value(spec.template.spec.serviceAccountName)' 2>/dev/null || true)

if [ -z "$MCP_SA" ]; then
    PROJECT_NUMBER=$(gcloud projects describe ${PROJECT_ID} --format='value(projectNumber)')
    MCP_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
fi

echo "MCP service account: ${MCP_SA}"

gcloud run services add-iam-policy-binding ${VECTOR_SERVICE} \
    --region=${REGION} \
    --member="serviceAccount:${MCP_SA}" \
    --role="roles/run.invoker" \
    --project=${PROJECT_ID}

# ============================================================
# 3. Cloud Run domain mapping for echolocate.app
# ============================================================
echo ""
echo "Setting up domain mapping for ${DOMAIN}..."

if gcloud beta run domain-mappings describe --domain=${DOMAIN} --region=${REGION} --project=${PROJECT_ID} &>/dev/null; then
    echo "  Domain mapping already exists for ${DOMAIN}"
else
    gcloud beta run domain-mappings create \
        --service=${FRONTEND_SERVICE} \
        --domain=${DOMAIN} \
        --region=${REGION} \
        --project=${PROJECT_ID}
    echo "  Created domain mapping: ${DOMAIN} -> ${FRONTEND_SERVICE}"
fi

# ============================================================
# Done
# ============================================================
echo ""
echo "========================================="
echo "IAP + Domain setup complete!"
echo "========================================="
echo ""
echo "Frontend: https://${DOMAIN} (IAP-protected)"
echo "Vector:   public (CORS restricted to https://${DOMAIN})"
echo ""
echo "DNS: Configure the following records at your registrar:"
echo "  Run: gcloud beta run domain-mappings describe --domain=${DOMAIN} --region=${REGION} --project=${PROJECT_ID}"
echo "  to see the required DNS records."
echo ""
echo "Verify IAP is working:"
echo "  curl -s -o /dev/null -w '%{http_code}' https://${DOMAIN}/  (expect 302)"
echo "========================================="
