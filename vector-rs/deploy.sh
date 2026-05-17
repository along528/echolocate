#!/bin/bash
set -e

# Ensure we are in the script's directory
cd "$(dirname "$0")"

SERVICE_NAME="cloud-crate-vector-rs"
REGION="us-central1"
PROJECT_ID=$(gcloud config get-value project)
IMAGE="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"

echo "Deploying $SERVICE_NAME..."

# Capture version metadata before changing directories
GIT_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
if [ -f data/index.duckdb ]; then
    INDEX_VERSION=$(stat -f %Sm -t %Y%m%d data/index.duckdb 2>/dev/null || stat -c %Y data/index.duckdb 2>/dev/null || echo "unknown")
else
    INDEX_VERSION="unknown"
fi
MODEL_VERSION="mert-v1-95m+clap-htsat"

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
    --no-cpu-throttling \
    --min-instances=0 \
    --set-env-vars INDEX_DB_PATH=/app/index.duckdb,DB_POOL_SIZE=4,GCP_PROJECT_ID=${PROJECT_ID},CORS_ALLOW_ORIGINS=https://echolocate.app,INDEX_VERSION=${INDEX_VERSION},MODEL_VERSION=${MODEL_VERSION},GIT_SHA=${GIT_SHA},LABELS_BUCKET=cloud-crate-vector-db

echo "✅ Deployment complete."
