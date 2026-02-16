#!/bin/bash
set -e

PROJECT_ID="cloud-crate-485418"
REGION="us-central1"
BUCKET_NAME="cloud-crate-vector-db"
PREFIX="fma/fma_full/"
JOB_NAME="fma-transfer"
ZIP_BLOB="fma-source/os.unil.cloud.switch.ch/fma/fma_full.zip"
# bust cache

echo "🔨 Building container..."
gcloud builds submit --tag gcr.io/$PROJECT_ID/fma-ingest .

echo "🚀 Creating or updating Cloud Run Job..."
if gcloud run jobs describe $JOB_NAME --region=$REGION &>/dev/null; then
    echo "Job exists, updating..."
    gcloud run jobs update $JOB_NAME \
        --image gcr.io/$PROJECT_ID/fma-ingest \
        --task-timeout=86400 \
        --cpu=2 \
        --memory=8Gi \
        --region=$REGION \
        --set-env-vars="BUCKET_NAME=$BUCKET_NAME,ZIP_BLOB=$ZIP_BLOB,PREFIX=$PREFIX,MAX_WORKERS=48"
else
    echo "Creating new job..."
    gcloud run jobs create $JOB_NAME \
        --image gcr.io/$PROJECT_ID/fma-ingest \
        --task-timeout=86400 \
        --cpu=2 \
        --memory=8Gi \
        --region=$REGION \
        --set-env-vars="BUCKET_NAME=$BUCKET_NAME,ZIP_BLOB=$ZIP_BLOB,PREFIX=$PREFIX,MAX_WORKERS=48"
fi

echo "▶️ Executing job..."
gcloud run jobs execute $JOB_NAME --region=$REGION

echo "✅ Job started! Monitor with:"
echo "gcloud run jobs executions list --job=$JOB_NAME --region=$REGION"
echo "gcloud logging read 'resource.type=cloud_run_job AND resource.labels.job_name=$JOB_NAME' --limit=50"
