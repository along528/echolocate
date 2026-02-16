#!/bin/bash
set -e

# Shared Load Balancer + IAP Setup
# Routes /* to frontend, /api/* to vector service (with path rewrite)
# Idempotent — safe to re-run if a previous attempt failed partway through.

PROJECT_ID="cloud-crate-485418"
REGION="us-central1"
FRONTEND_SERVICE="cloud-crate-frontend"
VECTOR_SERVICE="cloud-crate-vector"
MCP_SERVICE="cloud-crate-mcp"
LB_PREFIX="cloud-crate"

USER_EMAIL="${1:-}"
if [ -z "$USER_EMAIL" ]; then
    echo "Usage: ./setup_iap.sh <your-google-email>"
    exit 1
fi

echo "Setting up shared LB + IAP for Cloud Crate..."
echo "Authorized user: ${USER_EMAIL}"

# Helper: create a resource only if it doesn't already exist.
# Usage: create_if_missing <describe_cmd> <create_cmd>
create_if_missing() {
    local name="$1"; shift
    local describe_cmd="$1"; shift
    # remaining args are the create command
    if eval "$describe_cmd" &>/dev/null; then
        echo "  Already exists: ${name}"
    else
        echo "  Creating: ${name}"
        "$@"
    fi
}

# ============================================================
# 0. Tear down old frontend-only LB resources (if they exist)
# ============================================================
echo ""
echo "Cleaning up old frontend-only LB resources..."
OLD_PREFIX="${FRONTEND_SERVICE}"

# Delete in reverse dependency order; ignore errors if resources don't exist
gcloud compute forwarding-rules delete ${OLD_PREFIX}-forwarding \
    --global --project=${PROJECT_ID} --quiet 2>/dev/null || true
gcloud compute target-https-proxies delete ${OLD_PREFIX}-https-proxy \
    --project=${PROJECT_ID} --quiet 2>/dev/null || true
gcloud compute ssl-certificates delete ${OLD_PREFIX}-cert \
    --global --project=${PROJECT_ID} --quiet 2>/dev/null || true
gcloud compute url-maps delete ${OLD_PREFIX}-urlmap \
    --project=${PROJECT_ID} --quiet 2>/dev/null || true
gcloud compute backend-services remove-backend ${OLD_PREFIX}-backend \
    --global \
    --network-endpoint-group=${OLD_PREFIX}-neg \
    --network-endpoint-group-region=${REGION} \
    --project=${PROJECT_ID} --quiet 2>/dev/null || true
gcloud compute backend-services delete ${OLD_PREFIX}-backend \
    --global --project=${PROJECT_ID} --quiet 2>/dev/null || true
gcloud compute network-endpoint-groups delete ${OLD_PREFIX}-neg \
    --region=${REGION} --project=${PROJECT_ID} --quiet 2>/dev/null || true

echo "Old resources cleaned up."

# ============================================================
# 1. Static IP (reuse existing or create new)
# ============================================================
echo ""
echo "Setting up static IP..."
IP_NAME="${OLD_PREFIX}-ip"  # Reuse existing IP name to keep the address

if gcloud compute addresses describe ${IP_NAME} --global --project=${PROJECT_ID} &>/dev/null; then
    echo "Reusing existing static IP: ${IP_NAME}"
else
    echo "Creating new static IP: ${IP_NAME}"
    gcloud compute addresses create ${IP_NAME} \
        --global \
        --project=${PROJECT_ID}
fi

IP=$(gcloud compute addresses describe ${IP_NAME} \
    --global \
    --project=${PROJECT_ID} \
    --format='value(address)')
echo "Static IP: ${IP}"

# ============================================================
# 2. Serverless NEGs (idempotent)
# ============================================================
echo ""
echo "Setting up serverless NEGs..."

if ! gcloud compute network-endpoint-groups describe ${LB_PREFIX}-frontend-neg --region=${REGION} --project=${PROJECT_ID} &>/dev/null; then
    gcloud compute network-endpoint-groups create ${LB_PREFIX}-frontend-neg \
        --region=${REGION} \
        --network-endpoint-type=serverless \
        --cloud-run-service=${FRONTEND_SERVICE} \
        --project=${PROJECT_ID}
    echo "  Created: ${LB_PREFIX}-frontend-neg"
else
    echo "  Already exists: ${LB_PREFIX}-frontend-neg"
fi

if ! gcloud compute network-endpoint-groups describe ${LB_PREFIX}-vector-neg --region=${REGION} --project=${PROJECT_ID} &>/dev/null; then
    gcloud compute network-endpoint-groups create ${LB_PREFIX}-vector-neg \
        --region=${REGION} \
        --network-endpoint-type=serverless \
        --cloud-run-service=${VECTOR_SERVICE} \
        --project=${PROJECT_ID}
    echo "  Created: ${LB_PREFIX}-vector-neg"
else
    echo "  Already exists: ${LB_PREFIX}-vector-neg"
fi

# ============================================================
# 3. Backend services (idempotent)
# ============================================================
echo ""
echo "Setting up backend services..."

# Frontend backend
if ! gcloud compute backend-services describe ${LB_PREFIX}-frontend-backend --global --project=${PROJECT_ID} &>/dev/null; then
    gcloud compute backend-services create ${LB_PREFIX}-frontend-backend \
        --global \
        --project=${PROJECT_ID}
    echo "  Created: ${LB_PREFIX}-frontend-backend"
else
    echo "  Already exists: ${LB_PREFIX}-frontend-backend"
fi

# Add NEG to frontend backend (idempotent — add-backend is a no-op if already attached)
gcloud compute backend-services add-backend ${LB_PREFIX}-frontend-backend \
    --global \
    --network-endpoint-group=${LB_PREFIX}-frontend-neg \
    --network-endpoint-group-region=${REGION} \
    --project=${PROJECT_ID} 2>/dev/null || true

# Vector backend
if ! gcloud compute backend-services describe ${LB_PREFIX}-vector-backend --global --project=${PROJECT_ID} &>/dev/null; then
    gcloud compute backend-services create ${LB_PREFIX}-vector-backend \
        --global \
        --project=${PROJECT_ID}
    echo "  Created: ${LB_PREFIX}-vector-backend"
else
    echo "  Already exists: ${LB_PREFIX}-vector-backend"
fi

gcloud compute backend-services add-backend ${LB_PREFIX}-vector-backend \
    --global \
    --network-endpoint-group=${LB_PREFIX}-vector-neg \
    --network-endpoint-group-region=${REGION} \
    --project=${PROJECT_ID} 2>/dev/null || true

# ============================================================
# 4. URL map with path-based routing + path rewrite
# ============================================================
echo ""
echo "Setting up URL map with path-based routing..."

# Build the complete URL map as JSON and import it in one shot.
# This is idempotent — import replaces the existing URL map if present.
URLMAP_FILE="/tmp/cloud-crate-urlmap.json"

cat > "${URLMAP_FILE}" <<JSONEOF
{
  "name": "${LB_PREFIX}-urlmap",
  "defaultService": "projects/${PROJECT_ID}/global/backendServices/${LB_PREFIX}-frontend-backend",
  "hostRules": [
    {
      "hosts": ["*"],
      "pathMatcher": "api-matcher"
    }
  ],
  "pathMatchers": [
    {
      "name": "api-matcher",
      "defaultService": "projects/${PROJECT_ID}/global/backendServices/${LB_PREFIX}-frontend-backend",
      "pathRules": [
        {
          "paths": ["/api/*"],
          "service": "projects/${PROJECT_ID}/global/backendServices/${LB_PREFIX}-vector-backend",
          "routeAction": {
            "urlRewrite": {
              "pathPrefixRewrite": "/"
            }
          }
        }
      ]
    }
  ]
}
JSONEOF

# Create the URL map if it doesn't exist yet (import --quiet only updates existing)
if ! gcloud compute url-maps describe ${LB_PREFIX}-urlmap --project=${PROJECT_ID} &>/dev/null; then
    gcloud compute url-maps create ${LB_PREFIX}-urlmap \
        --default-service=${LB_PREFIX}-frontend-backend \
        --project=${PROJECT_ID}
    echo "  Created base URL map"
fi

# Import the full config (updates in place)
gcloud compute url-maps import ${LB_PREFIX}-urlmap \
    --source="${URLMAP_FILE}" \
    --project=${PROJECT_ID} \
    --quiet
echo "  URL map configured with /api/* -> vector (pathPrefixRewrite: /)"

# ============================================================
# 5. SSL certificate (nip.io domain, idempotent)
# ============================================================
DOMAIN="${IP//./-}.nip.io"
echo ""
echo "Setting up SSL certificate for ${DOMAIN}..."

if ! gcloud compute ssl-certificates describe ${LB_PREFIX}-cert --global --project=${PROJECT_ID} &>/dev/null; then
    gcloud compute ssl-certificates create ${LB_PREFIX}-cert \
        --domains=${DOMAIN} \
        --global \
        --project=${PROJECT_ID}
    echo "  Created: ${LB_PREFIX}-cert"
else
    echo "  Already exists: ${LB_PREFIX}-cert"
fi

# ============================================================
# 6. HTTPS proxy + forwarding rule (idempotent)
# ============================================================
echo ""
echo "Setting up HTTPS proxy and forwarding rule..."

if ! gcloud compute target-https-proxies describe ${LB_PREFIX}-https-proxy --project=${PROJECT_ID} &>/dev/null; then
    gcloud compute target-https-proxies create ${LB_PREFIX}-https-proxy \
        --ssl-certificates=${LB_PREFIX}-cert \
        --url-map=${LB_PREFIX}-urlmap \
        --project=${PROJECT_ID}
    echo "  Created: ${LB_PREFIX}-https-proxy"
else
    echo "  Already exists: ${LB_PREFIX}-https-proxy"
fi

if ! gcloud compute forwarding-rules describe ${LB_PREFIX}-forwarding --global --project=${PROJECT_ID} &>/dev/null; then
    gcloud compute forwarding-rules create ${LB_PREFIX}-forwarding \
        --global \
        --target-https-proxy=${LB_PREFIX}-https-proxy \
        --address=${IP_NAME} \
        --ports=443 \
        --project=${PROJECT_ID}
    echo "  Created: ${LB_PREFIX}-forwarding"
else
    echo "  Already exists: ${LB_PREFIX}-forwarding"
fi

# ============================================================
# 7. Enable IAP on both backend services
# ============================================================
echo ""
echo "Enabling IAP on backend services..."

gcloud compute backend-services update ${LB_PREFIX}-frontend-backend \
    --global \
    --iap=enabled \
    --project=${PROJECT_ID}

gcloud compute backend-services update ${LB_PREFIX}-vector-backend \
    --global \
    --iap=enabled \
    --project=${PROJECT_ID}

# ============================================================
# 8. Grant IAP access to the specified user
# ============================================================
echo ""
echo "Granting IAP access to ${USER_EMAIL}..."

gcloud iap web add-iam-policy-binding \
    --resource-type=backend-services \
    --service=${LB_PREFIX}-frontend-backend \
    --member="user:${USER_EMAIL}" \
    --role="roles/iap.httpsResourceAccessor" \
    --project=${PROJECT_ID}

gcloud iap web add-iam-policy-binding \
    --resource-type=backend-services \
    --service=${LB_PREFIX}-vector-backend \
    --member="user:${USER_EMAIL}" \
    --role="roles/iap.httpsResourceAccessor" \
    --project=${PROJECT_ID}

# ============================================================
# 9. Grant MCP service account run.invoker on vector service
# ============================================================
echo ""
echo "Granting MCP service account access to vector service..."

# Get the MCP service's service account (default compute SA unless overridden)
MCP_SA=$(gcloud run services describe ${MCP_SERVICE} \
    --region=${REGION} \
    --project=${PROJECT_ID} \
    --format='value(spec.template.spec.serviceAccountName)' 2>/dev/null || true)

if [ -z "$MCP_SA" ]; then
    # Fall back to default compute service account
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
# Done
# ============================================================
echo ""
echo "========================================="
echo "Shared LB + IAP setup complete!"
echo "========================================="
echo "Access URL: https://${DOMAIN}"
echo ""
echo "Routing:"
echo "  /*      -> ${FRONTEND_SERVICE} (frontend)"
echo "  /api/*  -> ${VECTOR_SERVICE}   (vector, rewritten to /*)"
echo ""
echo "NOTE: The managed SSL certificate can take 10-60 minutes to provision."
echo "Check status with:"
echo "  gcloud compute ssl-certificates describe ${LB_PREFIX}-cert --global --project=${PROJECT_ID}"
echo ""
echo "Verify IAP is working:"
echo "  curl -s -o /dev/null -w '%{http_code}' https://${DOMAIN}/  (expect 302)"
echo "  curl -s -o /dev/null -w '%{http_code}' https://${DOMAIN}/api/  (expect 302)"
echo ""
echo "OAuth consent screen:"
echo "  https://console.cloud.google.com/apis/credentials/consent?project=${PROJECT_ID}"
echo "========================================="
