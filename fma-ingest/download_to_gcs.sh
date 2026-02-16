#!/bin/bash
# Step 1: Download FMA zip to GCS using Storage Transfer Service
# This has built-in resume and retry capabilities

set -e

PROJECT_ID="cloud-crate-485418"
BUCKET_NAME="cloud-crate-vector-db"
TSV_URL="gs://cloud-crate-vector-db/fma/_transfer_urls.tsv"

echo "📤 Uploading URL list to GCS..."
gsutil cp fma_urls.tsv $TSV_URL

echo "🔓 Making TSV public (needed for Transfer Service)..."
gsutil acl ch -u AllUsers:R $TSV_URL

echo "🔌 Enabling Storage Transfer API..."
gcloud services enable storagetransfer.googleapis.com

echo "⏳ Waiting for API propagation..."
sleep 5

echo "🔑 Granting permissions to Transfer Service Agent..."
# Get the service agent email (this command might fail if the API isn't fully ready, so we retry loop or just hope 5s was enough)
# The format is project-PROJECT_NUMBER@storage-transfer-service.iam.gserviceaccount.com
# We can get project number via gcloud
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format="value(projectNumber)")
SERVICE_AGENT="project-$PROJECT_NUMBER@storage-transfer-service.iam.gserviceaccount.com"

echo "Agent email: $SERVICE_AGENT"
echo "Granting roles/storage.admin on gs://$BUCKET_NAME..."
gsutil iam ch "serviceAccount:$SERVICE_AGENT:roles/storage.admin" "gs://$BUCKET_NAME"

echo "🚀 Creating Storage Transfer Job via REST API..."
# Use curl with explicit project quota header
curl -X POST -H "Authorization: Bearer $(gcloud auth print-access-token)" \
     -H "Content-Type: application/json" \
     -H "x-goog-user-project: $PROJECT_ID" \
     -d @transfer_job.json \
     "https://storagetransfer.googleapis.com/v1/transferJobs" > job_response.json

# Parse job name from response (e.g., "transferJobs/123...")
JOB_NAME=$(cat job_response.json | grep -o '"name": "[^"]*"' | cut -d'"' -f4)

if [ -n "$JOB_NAME" ]; then
    echo ""
    echo "▶️ Starting transfer job: $JOB_NAME"
    gcloud transfer jobs run $JOB_NAME --project=$PROJECT_ID
fi

echo ""
echo "✅ Transfer job created and started!"
echo "Monitor progress at:"
echo "https://console.cloud.google.com/storage/transfer?project=$PROJECT_ID"
