#!/bin/bash
set -e

# Ensure we are in the script's directory
cd "$(dirname "$0")"

# Configuration
BUCKET_NAME="cloud-crate-vector-db"
DB_FILE="../data/cloudcrate.duckdb"
REGION="us-central1"

echo "Using Bucket Name: $BUCKET_NAME"

# 1. Create Bucket
if ! gcloud storage buckets describe gs://$BUCKET_NAME &>/dev/null; then
    echo "Creating bucket..."
    gcloud storage buckets create gs://$BUCKET_NAME --location=$REGION
else
    echo "Bucket exists."
fi

# 2. Check for Database File
if [ ! -f "$DB_FILE" ]; then
    echo "Error: Database file not found at $DB_FILE."
    echo "Please run 'python audio_embedding/generate_db.py' to generate it."
    exit 1
fi

# 3. Upload Database
echo "Uploading database to GCS..."
gcloud storage cp $DB_FILE gs://$BUCKET_NAME/cloudcrate.duckdb

echo "✅ Setup complete. Bucket: $BUCKET_NAME"
# Save bucket name for deploy script
echo "$BUCKET_NAME" > .bucket_name
