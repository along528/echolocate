#!/bin/bash
set -e

# Manual production deploy for vector-rs (the fallback). The primary path is the
# vector-rs-deploy.yml GitHub Actions workflow, which auto-deploys on merge to
# main by fetching the index from GCS. Use this script to deploy by hand from a
# machine that has the local ~1.4GB data/index.duckdb.

# Ensure we are in the script's directory
cd "$(dirname "$0")"

SERVICE_NAME="cloud-crate-vector-rs"
REGION="us-central1"
PROJECT_ID=$(gcloud config get-value project)
IMAGE="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"

echo "Deploying $SERVICE_NAME..."

# Capture version metadata before changing directories
GIT_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")

# --- Prerequisite: the baked index MUST exist and carry the x,y map columns ---
# vector-rs now selects x,y on EVERY track query (not just /map/backdrop), so an
# index baked without those columns makes ALL queries error at runtime. Fail loudly
# here rather than shipping a broken image. Regenerate the index with:
#   cd embeddings && python generate_projection.py && python generate_index_db.py
# Path is relative to vector-rs/ (this script's dir). The Docker build context is the
# repo root, so the index lives at <repo-root>/data/index.duckdb == ../data/index.duckdb
# here. The Dockerfile's `COPY data/index.duckdb` resolves against that same root.
INDEX_DB="../data/index.duckdb"
if [ ! -f "$INDEX_DB" ]; then
    echo "❌ $INDEX_DB not found — it gets baked into the image (INDEX_DB_PATH=/app/index.duckdb)." >&2
    echo "   Build it: cd embeddings && python generate_projection.py && python generate_index_db.py" >&2
    exit 1
fi

PYTHON=$(command -v python3 || command -v python || true)
if [ -n "$PYTHON" ]; then
    echo "Verifying $INDEX_DB has x,y map columns..."
    "$PYTHON" - "$INDEX_DB" <<'PYEOF'
import sys
try:
    import duckdb
except ImportError:
    print("⚠️  duckdb not importable; skipping x,y column verification. "
          "Activate .venv to enable this check.", file=sys.stderr)
    sys.exit(0)

db_path = sys.argv[1]
con = duckdb.connect(db_path, read_only=True)
tables = [r[0] for r in con.execute(
    "SELECT table_name FROM information_schema.tables WHERE table_name LIKE 'tracks%'"
).fetchall()]
if not tables:
    sys.exit(f"❌ {db_path} has no tracks tables.")
missing = []
for t in tables:
    # PRAGMA table_info rows are (cid, name, type, ...); the column name is r[1].
    cols = {r[1] for r in con.execute(f"PRAGMA table_info('{t}')").fetchall()}
    missing += [f"{t}.{c}" for c in ("x", "y") if c not in cols]
if missing:
    sys.exit(
        f"❌ {db_path} is missing map columns: {', '.join(missing)}.\n"
        "   The projection + index rebuild MUST run before deploy:\n"
        "   cd embeddings && python generate_projection.py && python generate_index_db.py"
    )
print(f"✓ x,y present on: {', '.join(tables)}")
PYEOF
else
    echo "⚠️  No python interpreter found; skipping x,y column verification." >&2
fi

INDEX_VERSION=$(stat -f %Sm -t %Y%m%d "$INDEX_DB" 2>/dev/null || stat -c %Y "$INDEX_DB" 2>/dev/null || echo "unknown")
MODEL_VERSION="mert-v1-95m+clap-htsat"

# Build from repo root so Docker context includes vector-rs/scripts/ (CLAP export) and data/
cd ..

# Build and push the image. Cloud Run only runs linux/amd64, so pin the platform
# rather than inherit the host's — an arm64 workstation would otherwise build and
# push an image Cloud Run cannot execute. On amd64 hosts this is a no-op; on arm64
# it builds under emulation (slow but correct).
echo "Building image..."
docker build --platform linux/amd64 -f vector-rs/Dockerfile -t "${IMAGE}" .
echo "Pushing image..."
docker push "${IMAGE}"

# Deploy to Cloud Run
gcloud run deploy $SERVICE_NAME \
    --image "${IMAGE}" \
    --region $REGION \
    --allow-unauthenticated \
    --ingress all \
    --execution-environment=gen2 \
    --memory=8Gi \
    --cpu=2 \
    --timeout=900 \
    --cpu-boost \
    --no-cpu-throttling \
    --min-instances=0 \
    --set-env-vars "^@^INDEX_DB_PATH=/app/index.duckdb@DB_POOL_SIZE=4@GCP_PROJECT_ID=${PROJECT_ID}@GEMINI_MODEL=gemini-2.5-flash@CORS_ALLOW_ORIGINS=https://echolocate.app,https://echoes.echolocate.app,https://sonar.echolocate.app@INDEX_VERSION=${INDEX_VERSION}@MODEL_VERSION=${MODEL_VERSION}@GIT_SHA=${GIT_SHA}@LABELS_BUCKET=cloud-crate-vector-db"

echo "✅ Deployment complete."
