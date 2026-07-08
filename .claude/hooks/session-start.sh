#!/bin/bash
# SessionStart hook: provision the vector-rs native toolchain (libduckdb,
# onnxruntime, vss extension, CLAP ONNX model) and the sample index so a Claude
# Code on the web session can build, `cargo test`, run the Axum server, and curl
# its endpoints. Runs synchronously so deps are ready before the agent starts.
#
# Web-only. Non-fatal: if the sandbox's egress policy blocks a required host the
# hook reports it and lets the session start anyway (build/test simply won't work
# until the host is allowlisted — see vector-rs/README.md § Dev sandbox).
set -uo pipefail

# Only run in the remote (web) environment; a no-op for local CLI sessions.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

REPO="${CLAUDE_PROJECT_DIR:-$(pwd)}"

echo "[session-start] Provisioning vector-rs dev sandbox..."
bash "$REPO/vector-rs/scripts/setup-dev.sh" \
  || echo "[session-start] ⚠️  vector-rs provisioning incomplete (see output above)." >&2

# Persist the build/run env for this session's shells (the canonical mechanism
# in the web harness). setup-dev.sh also wires ~/.bashrc for other contexts.
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  cat >> "$CLAUDE_ENV_FILE" <<'ENV'
export DUCKDB_LIB_DIR=/usr/local/lib
export DUCKDB_INCLUDE_DIR=/usr/local/include
export LD_LIBRARY_PATH=/usr/local/lib:${LD_LIBRARY_PATH:-}
export ORT_DYLIB_PATH=/usr/local/lib/libonnxruntime.so
ENV
fi

exit 0
