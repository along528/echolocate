#!/bin/bash
set -e

# Ensure we are in the script's directory
cd "$(dirname "$0")"

SERVICE_NAME="mcp-helloworld"
REGION="us-central1"
PROJECT="cloud-crate-485418"
VECTOR_URL="https://cloudcrate-vector-403961692263.us-central1.run.app"

echo "Deploying $SERVICE_NAME..."

# Deploy to Cloud Run
# Note: We pass the PROJECT and VECTOR_SERVICE_URL as env vars.
# Secrets are handled by the app internally fetching from GSM, 
# but we can also mount them here if we prefer "standard" secret injection.
# The app handles GSM fetching if env vars are missing, so we just set the project.

gcloud run deploy $SERVICE_NAME \
    --source . \
    --region $REGION \
    --port 8080 \
    --allow-unauthenticated \
    --set-env-vars GOOGLE_CLOUD_PROJECT=$PROJECT,VECTOR_SERVICE_URL=$VECTOR_URL

echo "✅ Deployment complete."
