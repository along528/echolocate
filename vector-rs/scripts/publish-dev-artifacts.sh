#!/usr/bin/env bash
#
# Publish the prebuilt dev artifacts that setup-dev.sh fetches, so remote/dev
# sandboxes can provision the CLAP model (and vss extension) WITHOUT running the
# heavy torch export or reaching the DuckDB extension repo.
#
# Run once by a maintainer with write access to the bucket:
#   gcloud auth login   # (or ADC) with roles/storage.objectAdmin on the bucket
#   bash vector-rs/scripts/publish-dev-artifacts.sh
#
# Uploads to the exact paths setup-dev.sh reads:
#   $BUCKET/clap_text_onnx/{clap_text.onnx,clap_text.onnx.data,tokenizer.json}
#   $BUCKET/vss.duckdb_extension
set -euo pipefail

BUCKET="${DEV_ARTIFACTS_BUCKET:-gs://cloud-crate-vector-db/dev-artifacts}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

command -v gcloud >/dev/null 2>&1 || { echo "❌ gcloud not found." >&2; exit 1; }

# --- CLAP ONNX model --------------------------------------------------------
# Reuse an existing export dir, or produce one with the same script the
# Dockerfile stage-1 uses (needs torch/transformers from vector/requirements.txt).
CLAP_DIR="${CLAP_DIR:-$REPO_ROOT/vector-rs/clap_text_onnx}"
if [[ ! -f "$CLAP_DIR/clap_text.onnx" || ! -f "$CLAP_DIR/tokenizer.json" ]]; then
  echo "CLAP model not found at $CLAP_DIR — exporting (needs torch)..."
  PYTHON="$(command -v python3 || command -v python)"
  "$PYTHON" "$REPO_ROOT/vector/export_clap_text.py" --output-dir "$CLAP_DIR"
fi
echo "Uploading CLAP model → $BUCKET/clap_text_onnx/"
# clap_text.onnx* deliberately globs both the graph (clap_text.onnx) and its
# external weights (clap_text.onnx.data) — torch exports the ~500MB weights to a
# sibling .data file that ORT loads by relative path, so publishing the graph
# alone yields a weightless, unloadable model.
gcloud storage cp \
  "$CLAP_DIR"/clap_text.onnx* \
  "$CLAP_DIR/tokenizer.json" \
  "$BUCKET/clap_text_onnx/"

# --- DuckDB vss extension (optional) ---------------------------------------
# Lets sandboxes whose egress blocks extensions.duckdb.org load vss offline.
# Point VSS_EXT at a vss.duckdb_extension built for duckdb v1.2.x (the one
# setup-dev.sh / the Dockerfile install lands here by default).
VSS_EXT="${VSS_EXT:-$HOME/.duckdb/extensions/v1.2.2/linux_amd64_gcc4/vss.duckdb_extension}"
if [[ -f "$VSS_EXT" ]]; then
  echo "Uploading vss extension → $BUCKET/vss.duckdb_extension"
  gcloud storage cp "$VSS_EXT" "$BUCKET/vss.duckdb_extension"
else
  echo "⚠️  vss extension not found at $VSS_EXT — skipping."
  echo "   Install it (duckdb -c 'INSTALL vss;') and re-run with VSS_EXT=<path> to publish."
fi

echo "✅ Done. setup-dev.sh fetches these from $BUCKET."
