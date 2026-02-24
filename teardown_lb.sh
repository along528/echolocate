#!/bin/bash
# One-time teardown of old load balancer infrastructure.
# Deletes resources in reverse dependency order. Safe to re-run.

PROJECT_ID="cloud-crate-485418"
REGION="us-central1"
LB_PREFIX="cloud-crate"
OLD_PREFIX="cloud-crate-frontend"

echo "Tearing down load balancer resources..."

# Forwarding rule
echo "  Deleting forwarding rule..."
gcloud compute forwarding-rules delete ${LB_PREFIX}-forwarding \
    --global --project=${PROJECT_ID} --quiet 2>/dev/null || true

# HTTPS proxy
echo "  Deleting HTTPS proxy..."
gcloud compute target-https-proxies delete ${LB_PREFIX}-https-proxy \
    --project=${PROJECT_ID} --quiet 2>/dev/null || true

# SSL certificate
echo "  Deleting SSL certificate..."
gcloud compute ssl-certificates delete ${LB_PREFIX}-cert \
    --global --project=${PROJECT_ID} --quiet 2>/dev/null || true

# URL map
echo "  Deleting URL map..."
gcloud compute url-maps delete ${LB_PREFIX}-urlmap \
    --project=${PROJECT_ID} --quiet 2>/dev/null || true

# Frontend backend service (remove NEG first, then delete)
echo "  Deleting frontend backend service..."
gcloud compute backend-services remove-backend ${LB_PREFIX}-frontend-backend \
    --global \
    --network-endpoint-group=${LB_PREFIX}-frontend-neg \
    --network-endpoint-group-region=${REGION} \
    --project=${PROJECT_ID} --quiet 2>/dev/null || true
gcloud compute backend-services delete ${LB_PREFIX}-frontend-backend \
    --global --project=${PROJECT_ID} --quiet 2>/dev/null || true

# Vector backend service (remove NEG first, then delete)
echo "  Deleting vector backend service..."
gcloud compute backend-services remove-backend ${LB_PREFIX}-vector-backend \
    --global \
    --network-endpoint-group=${LB_PREFIX}-vector-neg \
    --network-endpoint-group-region=${REGION} \
    --project=${PROJECT_ID} --quiet 2>/dev/null || true
gcloud compute backend-services delete ${LB_PREFIX}-vector-backend \
    --global --project=${PROJECT_ID} --quiet 2>/dev/null || true

# NEGs
echo "  Deleting NEGs..."
gcloud compute network-endpoint-groups delete ${LB_PREFIX}-frontend-neg \
    --region=${REGION} --project=${PROJECT_ID} --quiet 2>/dev/null || true
gcloud compute network-endpoint-groups delete ${LB_PREFIX}-vector-neg \
    --region=${REGION} --project=${PROJECT_ID} --quiet 2>/dev/null || true

# Static IP
echo "  Deleting static IP..."
gcloud compute addresses delete ${OLD_PREFIX}-ip \
    --global --project=${PROJECT_ID} --quiet 2>/dev/null || true

echo ""
echo "Load balancer teardown complete."
