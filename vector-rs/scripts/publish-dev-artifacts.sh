#!/usr/bin/env bash
#
# Publish the prebuilt dev artifacts that setup-dev.sh fetches, so remote/dev
# sandboxes can provision libduckdb, onnxruntime, vss, and the CLAP model
# WITHOUT running the heavy torch export or reaching github.com/duckdb/duckdb,
# github.com/microsoft/onnxruntime, or the DuckDB extension repo. Mirroring
# libduckdb + onnxruntime here isn't just an egress convenience: Claude Code on
# the web scopes a session's GitHub access to a single owner's repos, so those
# two cross-owner github.com downloads 403 UNCONDITIONALLY there (not a network
# policy checkbox, and `add_repo` can't add a cross-owner repo either).
#
# libduckdb + onnxruntime are uploaded PUBLIC (--predefined-acl=publicRead) so
# setup-dev.sh can fetch them with plain curl — no gcloud/ADC needed in the
# sandbox at all, which matters since some sandboxes don't even have `gcloud`
# installed. This is scoped to those two objects ONLY. This bucket also serves
# the private audio corpus vector-rs streams in production (GCS_AUDIO_PREFIX) —
# never make the bucket itself public, and never add --predefined-acl=publicRead
# to any other upload in this script. (If the bucket enforces Uniform
# bucket-level access, per-object ACLs are rejected outright; in that case
# publish these two objects to a separate, dedicated public bucket instead of
# changing this bucket's access model.)
#
# vss + the CLAP model stay private, fetched via authenticated `gcloud storage
# cp` (ADC) — unchanged from before.
#
# Run once by a maintainer with write access to the bucket:
#   gcloud auth login   # (or ADC) with roles/storage.objectAdmin on the bucket
#   bash vector-rs/scripts/publish-dev-artifacts.sh
#
# Uploads to the exact paths setup-dev.sh reads:
#   $BUCKET/libduckdb-linux-amd64.zip                (public)
#   $BUCKET/onnxruntime-linux-x64-<ORT_VERSION>.tgz  (public)
#   $BUCKET/clap_text_onnx/{clap_text.onnx,clap_text.onnx.data,tokenizer.json}
#   $BUCKET/vss.duckdb_extension
set -euo pipefail

DUCKDB_VERSION="1.2.2"
ORT_VERSION="1.23.0"
BUCKET="${DEV_ARTIFACTS_BUCKET:-gs://cloud-crate-vector-db/dev-artifacts}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

command -v gcloud >/dev/null 2>&1 || { echo "❌ gcloud not found." >&2; exit 1; }

# --- libduckdb (PUBLIC — see the scope warning above) ------------------------
# Re-download from github.com/duckdb/duckdb (this machine isn't subject to the
# cross-owner restriction) and re-upload verbatim, so setup-dev.sh's GCS fetch
# unzips it identically to the GitHub fallback.
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
echo "Fetching libduckdb $DUCKDB_VERSION from github.com..."
curl -fSL "https://github.com/duckdb/duckdb/releases/download/v${DUCKDB_VERSION}/libduckdb-linux-amd64.zip" \
  -o "$tmp/libduckdb-linux-amd64.zip"
echo "Uploading libduckdb → $BUCKET/libduckdb-linux-amd64.zip (public)"
gcloud storage cp --predefined-acl=publicRead \
  "$tmp/libduckdb-linux-amd64.zip" "$BUCKET/libduckdb-linux-amd64.zip"

# --- onnxruntime (PUBLIC — see the scope warning above) -----------------------
echo "Fetching onnxruntime $ORT_VERSION from github.com..."
curl -fSL "https://github.com/microsoft/onnxruntime/releases/download/v${ORT_VERSION}/onnxruntime-linux-x64-${ORT_VERSION}.tgz" \
  -o "$tmp/onnxruntime-linux-x64-${ORT_VERSION}.tgz"
echo "Uploading onnxruntime → $BUCKET/onnxruntime-linux-x64-${ORT_VERSION}.tgz (public)"
gcloud storage cp --predefined-acl=publicRead \
  "$tmp/onnxruntime-linux-x64-${ORT_VERSION}.tgz" "$BUCKET/onnxruntime-linux-x64-${ORT_VERSION}.tgz"

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
