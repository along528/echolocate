#!/bin/bash
set -e

echo "🚀 Starting Cloud Crate Deployment..."

# 1. Deploy Vector Service
echo "📦 Deploying Vector Service..."
cd vector_service
./deploy.sh
cd ..

# Capture Vector Service URL
echo "🔍 Retrieving Vector Service URL..."
VECTOR_URL=$(gcloud run services describe cloudcrate-vector --region us-central1 --format 'value(status.url)')
echo "✅ Vector Service URL: $VECTOR_URL"

# 2. Deploy MCP Server
echo "📦 Deploying MCP Server (cloud-crate-mcp)..."
cd mcp
# Pass the URL to the inner script
export VECTOR_SERVICE_URL=$VECTOR_URL
./deploy.sh
cd ..

echo "✅ All services deployed!"
echo "Cloud Crate MCP: $(gcloud run services describe cloud-crate-mcp --region us-central1 --format 'value(status.url)')"
