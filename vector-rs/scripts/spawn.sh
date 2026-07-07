#!/bin/bash
#
# spawn.sh — launched once per Managed Agents session by the poller
# (`ant beta:worker poll --on-work spawn.sh`, see run-worker.sh).
#
# The poller injects the session's identifiers into this script's environment:
#   ANTHROPIC_SESSION_ID, ANTHROPIC_WORK_ID, ANTHROPIC_ENVIRONMENT_ID,
#   ANTHROPIC_ENVIRONMENT_KEY  (and optionally ANTHROPIC_BASE_URL).
# We forward exactly those into a fresh vector-rs worker container. We deliberately
# do NOT forward ANTHROPIC_API_KEY — the org key must never reach agent tool calls;
# the worker authenticates to its queue with the environment key alone.
set -euo pipefail

IMAGE="${VECTOR_RS_WORKER_IMAGE:-vector-rs-worker}"
# Where session deliverables (written by the agent to /mnt/session/outputs) land
# on the host, one dir per session.
OUTPUTS_ROOT="${OUTPUTS_ROOT:-/tmp/vector-rs-sessions}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# Stage the vector-rs checkout into /workspace. Default: bind-mount the working
# copy (fast, for local dev). To pin a specific commit instead — the reproducible
# path — check that SHA out into a temp dir and set REPO_MOUNT to it before the
# poller starts (the session's metadata.commit is available via the Work API; see
# managed-agent/README.md § Pinning a commit).
REPO_MOUNT="${REPO_MOUNT:-$REPO_ROOT}"

SESSION_OUTPUTS="$OUTPUTS_ROOT/${ANTHROPIC_SESSION_ID:?poller must set ANTHROPIC_SESSION_ID}"
mkdir -p "$SESSION_OUTPUTS"

exec docker run --rm \
  -e ANTHROPIC_SESSION_ID \
  -e ANTHROPIC_WORK_ID \
  -e ANTHROPIC_ENVIRONMENT_ID \
  -e ANTHROPIC_ENVIRONMENT_KEY \
  -e ANTHROPIC_BASE_URL \
  -v "$SESSION_OUTPUTS":/mnt/session/outputs \
  -v "$REPO_MOUNT":/workspace \
  "$IMAGE"
