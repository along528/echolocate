#!/bin/bash

# Navigate to the directory where the script is located
cd "$(dirname "$0")"

# Activate virtual environment if present (optional but recommended for local dev)
if [ -d "../.venv" ]; then
    source ../.venv/bin/activate
fi

# Set Environment Variables for Local Dev
export DB_PATH="../data/cloudcrate.duckdb"
export CORS_ALLOW_ORIGINS="*" # Enable CORS for all origins in local dev
export GCP_PROJECT_ID=cloud-crate-485418

echo "Starting Vector Service on http://localhost:8001..."
uvicorn main:app --reload --port 8001
