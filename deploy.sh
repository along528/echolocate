#!/bin/bash
set -e

echo "🚀 Starting EchoLocate Deployment..."

# 1. Deploy Vector Service
echo "📦 Deploying Vector Service..."
cd vector-rs
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

# 3. Deploy Firestore Rules
echo "📦 Deploying Firestore Rules..."
cd firestore
./deploy.sh
cd ..

echo "✅ All services deployed!"
echo "EchoLocate MCP: $(gcloud run services describe cloud-crate-mcp --region us-central1 --format 'value(status.url)')"
