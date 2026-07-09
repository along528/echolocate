#!/usr/bin/env bash
#
# Publish the production baked index (data/index.duckdb, ~1.4GB) to a PRIVATE GCS
# object so the vector-rs-deploy.yml GitHub Actions workflow can fetch it and bake
# it into the production image. Run this once, and again whenever the index is
# regenerated (new embeddings / projection):
#
#   cd embeddings && python generate_projection.py && python generate_index_db.py
#   bash vector-rs/scripts/publish-index.sh   # needs storage.objectAdmin on the bucket
#
# Unlike publish-dev-artifacts.sh (which uploads PUBLIC, open-source dev deps),
# this object is DERIVED FROM THE PRIVATE CATALOG — it is uploaded PRIVATE (no
# --predefined-acl=publicRead). The bucket already hosts the private audio corpus;
# never make this object public. CI reads it via the gha-sonar-deployer WIF SA,
# which has storage.admin on the bucket.
#
# Each upload creates a new object generation; the deploy workflow uses that
# generation number as INDEX_VERSION to detect when the index has changed.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

INDEX_DB="$REPO_ROOT/data/index.duckdb"
INDEX_GCS="${INDEX_GCS:-gs://cloud-crate-vector-db/vector-rs-index/index.duckdb}"

command -v gcloud >/dev/null 2>&1 || { echo "❌ gcloud not found." >&2; exit 1; }

if [ ! -f "$INDEX_DB" ]; then
    echo "❌ $INDEX_DB not found — it gets baked into the production image." >&2
    echo "   Build it: cd embeddings && python generate_projection.py && python generate_index_db.py" >&2
    exit 1
fi

# --- Verify the index carries the x,y map columns before publishing ----------
# vector-rs selects x,y on EVERY track query, so an index baked without those
# columns makes ALL queries error at runtime. Fail loudly here (same check as
# vector-rs/deploy.sh) rather than shipping a broken index to production.
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
        "   The projection + index rebuild MUST run before publishing:\n"
        "   cd embeddings && python generate_projection.py && python generate_index_db.py"
    )
print(f"✓ x,y present on: {', '.join(tables)}")
PYEOF
else
    echo "⚠️  No python interpreter found; skipping x,y column verification." >&2
fi

# --- Upload (PRIVATE) --------------------------------------------------------
echo "Uploading index → $INDEX_GCS (private, ~1.4GB — this can take a while)..."
gcloud storage cp "$INDEX_DB" "$INDEX_GCS"

GENERATION=$(gcloud storage objects describe "$INDEX_GCS" --format='value(generation)')
echo "✅ Done. Published generation $GENERATION."
echo "   Trigger a deploy to pick it up: run the vector-rs-deploy workflow"
echo "   (Actions → vector-rs-deploy → Run workflow), or merge a vector-rs change."
