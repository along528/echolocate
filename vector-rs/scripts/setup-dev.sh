#!/usr/bin/env bash
#
# Provision the native dependencies needed to build, test, run, and query
# vector-rs in a development sandbox (a Claude Code web session, a container,
# a laptop). Idempotent and safe to run repeatedly — from a SessionStart hook,
# a Dockerfile, or by hand.
#
# What it does, and what each piece unblocks:
#   1. libduckdb 1.2.2  -> /usr/local/lib (+ headers)   REQUIRED to compile/test
#   2. onnxruntime 1.23.0 -> /usr/local/lib             required only to RUN
#   3. DuckDB vss extension -> ~/.duckdb/extensions      required only to RUN
#   4. CLAP ONNX model -> vector-rs/clap_text_onnx/      required only to RUN
#   5. sample index (committed) presence check           REQUIRED to query
#   6. wire ~/.bashrc to source scripts/dev-env.sh
#
# The `ort` crate uses load-dynamic (dlopen at runtime), so onnxruntime is NOT
# needed to `cargo build`/`cargo test` — only to launch the server. Steps that
# only affect running the server WARN on failure instead of aborting, so a
# constrained environment can still build and test.
#
# Network: all four fetch steps try the GCS dev-artifacts bucket first (needs
# ADC), falling back to GitHub release assets. GCS-first matters beyond ADC
# convenience: Claude Code on the web scopes a session's GitHub access to a
# single owner's repos, so github.com/duckdb/duckdb and
# github.com/microsoft/onnxruntime 403 UNCONDITIONALLY there — not a network
# policy checkbox, and `add_repo` can't add a cross-owner repo either
# (cross-tier adds are rejected). GitHub remains a working fallback on
# substrates without that restriction (laptop, Dockerfile.dev, generic CI). If
# your sandbox's egress policy blocks a host outright, that step warns and you
# deal with the runtime dep separately (see vector-rs/README.md).

set -euo pipefail

DUCKDB_VERSION="1.2.2"
ORT_VERSION="1.23.0"
DUCKDB_CLI_VERSION="$DUCKDB_VERSION"   # must match libduckdb: extension is written to v<CLI>/, engine looks under v<DUCKDB_VERSION>/
GCS_ARTIFACTS="gs://cloud-crate-vector-db/dev-artifacts"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VECTOR_RS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$VECTOR_RS_DIR/.." && pwd)"

SUDO=""
if [[ "$(id -u)" -ne 0 ]]; then
  command -v sudo >/dev/null 2>&1 && SUDO="sudo"
fi

log()  { printf '\033[1;36m[setup-dev]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[setup-dev] ⚠️  %s\033[0m\n' "$*" >&2; }

fetch() { # fetch <url> <dest>
  curl -fSL --retry 3 --retry-delay 2 "$1" -o "$2"
}

# --- 0. System build toolchain (REQUIRED to build/test) ---------------------
# The Rust build links openssl-sys (pkg-config + libssl-dev) and compiles native
# C deps (cmake, g++); the steps below also use curl + unzip. Dockerfile.dev
# apt-installs these, so a bare provisioning host must too — otherwise every step
# here "succeeds" but `cargo build` later fails with "pkg-config could not be
# found". Only apt is handled automatically; warn on other package managers.
if command -v apt-get >/dev/null 2>&1; then
  missing=()
  for t in pkg-config cmake g++ curl unzip; do
    command -v "$t" >/dev/null 2>&1 || missing+=("$t")
  done
  # libssl-dev ships headers, not a binary, so probe it separately.
  { command -v dpkg >/dev/null 2>&1 && dpkg -s libssl-dev >/dev/null 2>&1; } || missing+=("libssl-dev")
  if [[ ${#missing[@]} -gt 0 ]]; then
    log "Installing system build deps: ${missing[*]}"
    $SUDO apt-get update -qq \
      && $SUDO apt-get install -y -qq pkg-config libssl-dev cmake g++ curl unzip ca-certificates \
      || warn "apt-get install of build deps failed; cargo build/test will fail until they are present."
  else
    log "System build deps present."
  fi
else
  warn "Non-apt system: ensure pkg-config, libssl-dev, cmake, g++, curl, unzip are installed to build vector-rs."
fi

# --- 1. Rust toolchain (usually already present in web envs) ----------------
if ! command -v cargo >/dev/null 2>&1; then
  log "Installing Rust toolchain via rustup..."
  curl -fsSL https://sh.rustup.rs | sh -s -- -y --default-toolchain stable
  # shellcheck disable=SC1091
  source "$HOME/.cargo/env"
else
  log "Rust: $(cargo --version)"
fi

# --- 2. libduckdb (REQUIRED to build/test) ----------------------------------
if [[ -f /usr/local/lib/libduckdb.so && -f /usr/local/include/duckdb.h ]]; then
  log "libduckdb already installed."
else
  log "Installing libduckdb $DUCKDB_VERSION..."
  tmp="$(mktemp -d)"
  if command -v gcloud >/dev/null 2>&1 && \
     gcloud storage cp "$GCS_ARTIFACTS/libduckdb-linux-amd64.zip" "$tmp/libduckdb.zip" 2>/dev/null; then
    log "libduckdb fetched from GCS dev-artifacts."
  elif fetch "https://github.com/duckdb/duckdb/releases/download/v${DUCKDB_VERSION}/libduckdb-linux-amd64.zip" "$tmp/libduckdb.zip"; then
    log "libduckdb fetched from github.com."
  else
    warn "Failed to download libduckdb — this is REQUIRED to compile vector-rs."
    warn "GCS dev-artifacts had no mirror and github.com/duckdb/duckdb is unreachable"
    warn "(on Claude Code on the web, cross-owner GitHub repos are blocked outright —"
    warn "see vector-rs/README.md § Dev Sandbox). Publish the mirror with"
    warn "publish-dev-artifacts.sh, or use a substrate without the per-owner restriction."
    rm -rf "$tmp"
    exit 1
  fi
  unzip -oq "$tmp/libduckdb.zip" -d "$tmp/libduckdb"
  $SUDO cp "$tmp/libduckdb/libduckdb.so" /usr/local/lib/
  $SUDO cp "$tmp/libduckdb/duckdb.h" "$tmp/libduckdb/duckdb.hpp" /usr/local/include/
  $SUDO ldconfig
  rm -rf "$tmp"
  log "libduckdb installed."
fi

# --- 3. onnxruntime (required only to RUN) ----------------------------------
if ls /usr/local/lib/libonnxruntime.so* >/dev/null 2>&1; then
  log "onnxruntime already installed."
else
  log "Installing onnxruntime $ORT_VERSION..."
  tmp="$(mktemp -d)"
  if command -v gcloud >/dev/null 2>&1 && \
     gcloud storage cp "$GCS_ARTIFACTS/onnxruntime-linux-x64-${ORT_VERSION}.tgz" "$tmp/ort.tgz" 2>/dev/null; then
    log "onnxruntime fetched from GCS dev-artifacts."
    tar xzf "$tmp/ort.tgz" -C "$tmp"
    $SUDO cp "$tmp"/onnxruntime-linux-x64-${ORT_VERSION}/lib/libonnxruntime.so* /usr/local/lib/
    $SUDO ldconfig
    log "onnxruntime installed."
  elif fetch "https://github.com/microsoft/onnxruntime/releases/download/v${ORT_VERSION}/onnxruntime-linux-x64-${ORT_VERSION}.tgz" "$tmp/ort.tgz"; then
    tar xzf "$tmp/ort.tgz" -C "$tmp"
    $SUDO cp "$tmp"/onnxruntime-linux-x64-${ORT_VERSION}/lib/libonnxruntime.so* /usr/local/lib/
    $SUDO ldconfig
    log "onnxruntime installed."
  else
    warn "Could not fetch onnxruntime from GCS or github.com; the server won't run"
    warn "until it is present (build/test still work). On Claude Code on the web,"
    warn "microsoft/onnxruntime is unreachable outright (cross-owner GitHub restriction)"
    warn "— publish the mirror with publish-dev-artifacts.sh."
  fi
  rm -rf "$tmp"
fi

# --- 4. DuckDB vss extension (required only to RUN) -------------------------
# vector-rs runs `INSTALL vss; LOAD vss;` on every connection. Pre-placing the
# extension lets LOAD succeed offline. Try GCS first, then the CLI (which hits
# the DuckDB extension repository).
EXT_DIR="$HOME/.duckdb/extensions/v${DUCKDB_VERSION}/linux_amd64_gcc4"
if [[ -f "$EXT_DIR/vss.duckdb_extension" ]]; then
  log "vss extension already installed."
else
  log "Installing DuckDB vss extension..."
  mkdir -p "$EXT_DIR"
  if command -v gcloud >/dev/null 2>&1 && \
     gcloud storage cp "$GCS_ARTIFACTS/vss.duckdb_extension" "$EXT_DIR/vss.duckdb_extension" 2>/dev/null; then
    log "vss extension fetched from GCS dev-artifacts."
  else
    tmp="$(mktemp -d)"
    if fetch "https://github.com/duckdb/duckdb/releases/download/v${DUCKDB_CLI_VERSION}/duckdb_cli-linux-amd64.zip" "$tmp/duckdb.zip" && \
       unzip -oq "$tmp/duckdb.zip" -d "$tmp" && \
       "$tmp/duckdb" -c "INSTALL vss;" 2>/dev/null; then
      cp -r "$HOME"/.duckdb/extensions/*/*/vss.duckdb_extension "$EXT_DIR/" 2>/dev/null || true
      log "vss extension installed via DuckDB CLI."
    else
      warn "Could not install vss (egress to the extension repo, or to"
      warn "github.com/duckdb/duckdb for the CLI, may be blocked — the latter is"
      warn "unconditional on Claude Code on the web; see the GCS note above)."
      warn "The server needs it at runtime; allowlist extensions.duckdb.org or publish it to $GCS_ARTIFACTS."
    fi
    rm -rf "$tmp"
  fi
fi

# --- 5. CLAP ONNX model (required only to RUN) ------------------------------
CLAP_DIR="$VECTOR_RS_DIR/clap_text_onnx"
if [[ -f "$CLAP_DIR/clap_text.onnx" && -f "$CLAP_DIR/tokenizer.json" ]]; then
  log "CLAP ONNX model already present."
else
  log "Fetching CLAP ONNX model..."
  mkdir -p "$CLAP_DIR"
  if command -v gcloud >/dev/null 2>&1 && \
     gcloud storage cp "$GCS_ARTIFACTS/clap_text_onnx/*" "$CLAP_DIR/" 2>/dev/null; then
    log "CLAP model fetched from GCS dev-artifacts."
  else
    warn "Could not fetch the CLAP model. /semantic-search and server startup need it."
    warn "Options: provide GCP ADC (has access to $GCS_ARTIFACTS/clap_text_onnx/),"
    warn "  or export it locally: python vector/export_clap_text.py --output-dir $CLAP_DIR"
  fi
fi

# --- 6. Sample index (REQUIRED to query; committed to the repo) -------------
SAMPLE="$VECTOR_RS_DIR/testdata/sample_index.duckdb"
if [[ -f "$SAMPLE" ]]; then
  log "Sample index present ($(du -h "$SAMPLE" | cut -f1))."
else
  warn "Sample index missing at $SAMPLE — generating a synthetic one..."
  python3 "$REPO_ROOT/embeddings/generate_sample_index.py" || \
    warn "Generation failed; run: pip install duckdb==$DUCKDB_VERSION numpy && python embeddings/generate_sample_index.py"
fi

# --- 7. Persist env for interactive shells ----------------------------------
DEV_ENV="$SCRIPT_DIR/dev-env.sh"
MARKER="# vector-rs dev-env (managed by setup-dev.sh)"
if ! grep -qF "$MARKER" "$HOME/.bashrc" 2>/dev/null; then
  {
    echo ""
    echo "$MARKER"
    echo "[ -f \"$DEV_ENV\" ] && source \"$DEV_ENV\""
  } >> "$HOME/.bashrc"
  log "Wired ~/.bashrc to source dev-env.sh."
fi

# shellcheck disable=SC1090
source "$DEV_ENV"

cat <<EOF

$(printf '\033[1;32m✅ vector-rs dev sandbox ready.\033[0m')

  Build + test:   cd $VECTOR_RS_DIR && cargo test
  Run the server: cd $VECTOR_RS_DIR && source scripts/dev-env.sh && cargo run
  Smoke test:     curl localhost:\${PORT:-8000}/ ; curl 'localhost:\${PORT:-8000}/search?query=blue&source=library'

Env is exported for this shell and future ones (via ~/.bashrc).
EOF
