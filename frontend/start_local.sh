#!/bin/bash

# Navigate to the repo root (assuming script is in frontend/)
cd "$(dirname "$0")/.."

# Activate the virtual environment
source .venv/bin/activate

# Navigate back to frontend
cd frontend

echo "Starting frontend on http://localhost:8082..."
python -m http.server 8082
