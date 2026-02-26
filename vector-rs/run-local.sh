#!/usr/bin/env bash
set -euo pipefail

IMAGE="cloud-crate-vector-rs"
CONTAINER="vector-rs-local"
PORT="${PORT:-8000}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [[ ! -f "$REPO_ROOT/data/index.duckdb" ]]; then
  echo "❌ Index DB not found at data/index.duckdb"
  echo "   Run: cd embeddings && python generate_index_db.py"
  exit 1
fi

# Build image (from repo root, since Dockerfile copies from vector/, vector-rs/, and data/)
echo "🔨 Building Docker image..."
docker build -f "$(dirname "$0")/Dockerfile" -t "$IMAGE" "$REPO_ROOT"

# Stop any existing container
docker rm -f "$CONTAINER" 2>/dev/null || true

# The baked index inside the image is used (INDEX_DB_PATH=/app/index.duckdb).
echo "🚀 Starting $CONTAINER on port $PORT..."
docker run --rm --name "$CONTAINER" \
  -p "$PORT:8080" \
  "$IMAGE"
