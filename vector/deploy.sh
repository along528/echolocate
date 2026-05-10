#!/bin/bash
set -e

# Ensure we are in the script's directory
cd "$(dirname "$0")"

SERVICE_NAME="cloud-crate-vector"
REGION="us-central1"

BUCKET_NAME="cloud-crate-vector-db"

echo "Deploying $SERVICE_NAME using bucket $BUCKET_NAME..."

# Deploy to Cloud Run
# We mount the bucket to /data
# And we use gen2 execution environment for file system mounts
# Memory/timeout increased for CLAP model loading
gcloud run deploy $SERVICE_NAME \
    --source . \
    --region $REGION \
    --allow-unauthenticated \
    --ingress all \
    --execution-environment=gen2 \
    --memory=2Gi \
    --cpu=1 \
    --timeout=900 \
    --cpu-boost \
    --cpu-throttling \
    --min-instances=0 \
    --add-volume=name=db-volume,type=cloud-storage,bucket=$BUCKET_NAME \
    --add-volume-mount=volume=db-volume,mount-path=/data \
    --set-env-vars DB_PATH=/data/cloudcrate.duckdb,GCP_PROJECT_ID=$(gcloud config get-value project),CORS_ALLOW_ORIGINS=https://echolocate.app

echo "✅ Deployment complete."
