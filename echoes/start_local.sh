#!/bin/bash
# Local dev: Vite on http://localhost:5173
# Point at a running vector-rs (locally on :8080, or override VITE_VECTOR_API_URL).
cd "$(dirname "$0")"
export VITE_VECTOR_API_URL="${VITE_VECTOR_API_URL:-http://localhost:8080}"
echo "Echoes dev server starting on http://localhost:5173"
echo "vector-rs API: $VITE_VECTOR_API_URL"
exec npx vite
