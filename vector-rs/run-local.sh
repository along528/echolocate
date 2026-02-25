#!/usr/bin/env bash
set -euo pipefail

IMAGE="cloud-crate-vector-rs"
CONTAINER="vector-rs-local"
PORT="${PORT:-8000}"
DB_PATH="${DB_PATH:-$(cd "$(dirname "$0")/.." && pwd)/data/cloudcrate.duckdb}"

if [[ ! -f "$DB_PATH" ]]; then
  echo "❌ Database not found at $DB_PATH"
  echo "   Run: cd embeddings && python generate_db.py"
  exit 1
fi

DB_DIR="$(dirname "$DB_PATH")"
DB_FILE="$(basename "$DB_PATH")"

# Build image (from repo root, since Dockerfile copies from vector/ and vector-rs/)
echo "🔨 Building Docker image..."
docker build -f "$(dirname "$0")/Dockerfile" -t "$IMAGE" "$(dirname "$0")/.."

# Stop any existing container
docker rm -f "$CONTAINER" 2>/dev/null || true

echo "🚀 Starting $CONTAINER on port $PORT..."
docker run --rm --name "$CONTAINER" \
  -p "$PORT:8080" \
  -v "$DB_DIR:/data:ro" \
  -e "DB_PATH=/data/$DB_FILE" \
  "$IMAGE"
