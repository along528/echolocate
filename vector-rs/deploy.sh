#!/bin/bash
set -e

# Ensure we are in the script's directory
cd "$(dirname "$0")"

SERVICE_NAME="cloud-crate-vector-rs"
REGION="us-central1"
BUCKET_NAME="cloud-crate-vector-db"
PROJECT_ID=$(gcloud config get-value project)
IMAGE="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"

echo "Deploying $SERVICE_NAME using bucket $BUCKET_NAME..."

# Build from repo root so Docker context includes both vector/ and vector-rs/
cd ..

# Build and push the image
echo "Building image..."
docker build -f vector-rs/Dockerfile -t "${IMAGE}" .
echo "Pushing image..."
docker push "${IMAGE}"

# Deploy to Cloud Run
gcloud run deploy $SERVICE_NAME \
    --image "${IMAGE}" \
    --region $REGION \
    --allow-unauthenticated \
    --ingress all \
    --execution-environment=gen2 \
    --memory=8Gi \
    --cpu=2 \
    --timeout=900 \
    --cpu-boost \
    --cpu-throttling \
    --min-instances=0 \
    --add-volume=name=db-volume,type=cloud-storage,bucket=$BUCKET_NAME \
    --add-volume-mount=volume=db-volume,mount-path=/data \
    --set-env-vars DB_PATH=/data/cloudcrate.duckdb,DB_POOL_SIZE=4,GCP_PROJECT_ID=${PROJECT_ID},CORS_ALLOW_ORIGINS=https://echolocate.app

echo "✅ Deployment complete."
