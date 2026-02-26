#!/usr/bin/env bash
set -euo pipefail

IMAGE="cloud-crate-vector-rs"
CONTAINER="vector-rs-local"
PORT="${PORT:-8000}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
INDEX_DB_PATH="${INDEX_DB_PATH:-$REPO_ROOT/data/index.duckdb}"
DB_PATH="${DB_PATH:-$REPO_ROOT/data/cloudcrate.duckdb}"

if [[ ! -f "$INDEX_DB_PATH" ]]; then
  echo "⚠️  Index DB not found at $INDEX_DB_PATH"
  echo "   Run: cd embeddings && python generate_index_db.py"
  echo "   Falling back to full DB at $DB_PATH"
  INDEX_DB_PATH=""
fi

if [[ -z "$INDEX_DB_PATH" && ! -f "$DB_PATH" ]]; then
  echo "❌ No database found. Run one of:"
  echo "   cd embeddings && python generate_index_db.py"
  echo "   cd embeddings && python generate_db.py"
  exit 1
fi

DB_DIR="$(dirname "$DB_PATH")"
DB_FILE="$(basename "$DB_PATH")"

# Build image (from repo root, since Dockerfile copies from vector/ and vector-rs/)
echo "🔨 Building Docker image..."
docker build -f "$(dirname "$0")/Dockerfile" -t "$IMAGE" "$REPO_ROOT"

# Stop any existing container
docker rm -f "$CONTAINER" 2>/dev/null || true

# The baked index inside the image is used by default (INDEX_DB_PATH=/app/index.duckdb).
# Mount the full DB directory for fallback access.
echo "🚀 Starting $CONTAINER on port $PORT..."
docker run --rm --name "$CONTAINER" \
  -p "$PORT:8080" \
  -v "$DB_DIR:/data:ro" \
  -e "DB_PATH=/data/$DB_FILE" \
  "$IMAGE"
