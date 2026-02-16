#!/bin/bash
set -e

PROJECT_ID="cloud-crate-485418"
REGION="us-central1"
SERVICE_NAME="cloud-crate-frontend"

# Prompt for user email if not provided as argument
USER_EMAIL="${1:-}"
if [ -z "$USER_EMAIL" ]; then
    echo "Usage: ./setup_iap.sh <your-google-email>"
    exit 1
fi

echo "Setting up IAP for ${SERVICE_NAME}..."
echo "Authorized user: ${USER_EMAIL}"

# 1. Reserve a global static IP
echo "Reserving static IP..."
gcloud compute addresses create ${SERVICE_NAME}-ip \
    --global \
    --project=${PROJECT_ID}

IP=$(gcloud compute addresses describe ${SERVICE_NAME}-ip \
    --global \
    --project=${PROJECT_ID} \
    --format='value(address)')
echo "Static IP: ${IP}"

# 2. Create serverless NEG pointing at the Cloud Run service
echo "Creating serverless NEG..."
gcloud compute network-endpoint-groups create ${SERVICE_NAME}-neg \
    --region=${REGION} \
    --network-endpoint-type=serverless \
    --cloud-run-service=${SERVICE_NAME} \
    --project=${PROJECT_ID}

# 3. Create backend service and attach NEG
echo "Creating backend service..."
gcloud compute backend-services create ${SERVICE_NAME}-backend \
    --global \
    --project=${PROJECT_ID}

gcloud compute backend-services add-backend ${SERVICE_NAME}-backend \
    --global \
    --network-endpoint-group=${SERVICE_NAME}-neg \
    --network-endpoint-group-region=${REGION} \
    --project=${PROJECT_ID}

# 4. Create URL map
echo "Creating URL map..."
gcloud compute url-maps create ${SERVICE_NAME}-urlmap \
    --default-service=${SERVICE_NAME}-backend \
    --project=${PROJECT_ID}

# 5. Create managed SSL cert with nip.io domain
DOMAIN="${IP//./-}.nip.io"
echo "Creating SSL certificate for ${DOMAIN}..."
gcloud compute ssl-certificates create ${SERVICE_NAME}-cert \
    --domains=${DOMAIN} \
    --global \
    --project=${PROJECT_ID}

# 6. Create HTTPS proxy
echo "Creating HTTPS proxy..."
gcloud compute target-https-proxies create ${SERVICE_NAME}-https-proxy \
    --ssl-certificates=${SERVICE_NAME}-cert \
    --url-map=${SERVICE_NAME}-urlmap \
    --project=${PROJECT_ID}

# 7. Create forwarding rule
echo "Creating forwarding rule..."
gcloud compute forwarding-rules create ${SERVICE_NAME}-forwarding \
    --global \
    --target-https-proxy=${SERVICE_NAME}-https-proxy \
    --address=${SERVICE_NAME}-ip \
    --ports=443 \
    --project=${PROJECT_ID}

# 8. Enable IAP on the backend service
echo "Enabling IAP on backend service..."
gcloud compute backend-services update ${SERVICE_NAME}-backend \
    --global \
    --iap=enabled \
    --project=${PROJECT_ID}

# 9. Grant IAP access to the specified user
echo "Granting IAP access to ${USER_EMAIL}..."
gcloud iap web add-iam-policy-binding \
    --resource-type=backend-services \
    --service=${SERVICE_NAME}-backend \
    --member="user:${USER_EMAIL}" \
    --role="roles/iap.httpsResourceAccessor" \
    --project=${PROJECT_ID}

echo ""
echo "========================================="
echo "IAP setup complete!"
echo "========================================="
echo "Access URL: https://${DOMAIN}"
echo ""
echo "NOTE: The managed SSL certificate can take 10-60 minutes to provision."
echo "Check status with:"
echo "  gcloud compute ssl-certificates describe ${SERVICE_NAME}-cert --global --project=${PROJECT_ID}"
echo ""
echo "Make sure the OAuth consent screen is configured in the GCP Console:"
echo "  https://console.cloud.google.com/apis/credentials/consent?project=${PROJECT_ID}"
echo "========================================="
