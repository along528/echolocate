#!/bin/bash
set -e

echo "🚀 Starting Cloud Crate Deployment..."

# 1. Deploy Vector Service
echo "📦 Deploying Vector Service..."
cd vector
./deploy.sh
cd ..

# Capture Vector Service URL using project-number format (required for Cloud Run internal routing)
echo "🔍 Retrieving Vector Service URL..."
PROJECT_NUMBER=$(gcloud projects describe $(gcloud config get-value project) --format 'value(projectNumber)')
VECTOR_URL="https://cloud-crate-vector-rs-${PROJECT_NUMBER}.us-central1.run.app"
echo "✅ Vector Service URL: $VECTOR_URL"

# 2. Deploy MCP Server
echo "📦 Deploying MCP Server (cloud-crate-mcp)..."
cd mcp
# Pass the URL to the inner script
export VECTOR_SERVICE_URL=$VECTOR_URL
./deploy.sh
cd ..

# 3. Deploy Discogs MCP Server
echo "📦 Deploying Discogs MCP Server..."
cd mcp-discogs
./deploy.sh
cd ..

# 4. Deploy Apple MCP Server
echo "📦 Deploying Apple MCP Server..."
cd mcp-apple
./deploy.sh
cd ..

# 5. Deploy Frontend
echo "📦 Deploying Frontend..."
cd frontend
./deploy.sh
cd ..

echo "✅ All services deployed!"
echo "Cloud Crate MCP: $(gcloud run services describe cloud-crate-mcp --region us-central1 --format 'value(status.url)')"
echo "Discogs MCP: $(gcloud run services describe cloud-crate-discogs-mcp --region us-central1 --format 'value(status.url)')"
echo "Apple MCP: $(gcloud run services describe cloud-crate-apple-mcp --region us-central1 --format 'value(status.url)')"
