#!/bin/bash
set -e

PROJECT_ID="cloud-crate-485418"
REGION="us-central1"
SERVICE_NAME="cloud-crate-frontend"

echo "Building and deploying frontend..."

# Build and push container
gcloud builds submit --tag gcr.io/${PROJECT_ID}/${SERVICE_NAME}

# Deploy to Cloud Run
gcloud beta run deploy ${SERVICE_NAME} \
    --image gcr.io/${PROJECT_ID}/${SERVICE_NAME} \
    --platform managed \
    --region ${REGION} \
    --allow-unauthenticated \
    --no-iap \
    --ingress all \
    --port 8080

echo "Frontend deployed!"
