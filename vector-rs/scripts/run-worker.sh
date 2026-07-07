#!/usr/bin/env bash
#
# Run the vector-rs Managed Agents worker poller on a Docker host.
#
# This is the always-on, sandbox-per-session pattern from
# platform.claude.com/docs/en/managed-agents/self-hosted-sandboxes: a long-running
# poller claims sessions assigned to the self-hosted environment and, for each,
# runs spawn.sh to launch one fresh vector-rs worker container. Anthropic's control
# plane drives the agent; every tool call executes inside your container.
#
# Prerequisites (see vector-rs/managed-agent/README.md for the full walkthrough):
#   - Docker running on this host.
#   - A `self_hosted` environment + its Console-generated environment key.
#   - export ANTHROPIC_ENVIRONMENT_ID=env_...
#   - export ANTHROPIC_ENVIRONMENT_KEY=sk-ant-oat01-...
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

: "${ANTHROPIC_ENVIRONMENT_ID:?set ANTHROPIC_ENVIRONMENT_ID (env_...) — see vector-rs/managed-agent/README.md}"
: "${ANTHROPIC_ENVIRONMENT_KEY:?set ANTHROPIC_ENVIRONMENT_KEY (sk-ant-oat01-...) — the worker credential, NOT your API key}"

# Credential boundary: the org API key must never be reachable from agent tool
# calls. It is used only OFF-host (to create sessions / read stats).
if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  echo "❌ ANTHROPIC_API_KEY is set on the worker host — refusing to start." >&2
  echo "   Unset it here; the worker authenticates with ANTHROPIC_ENVIRONMENT_KEY." >&2
  echo "   Run session-creation / stats commands from a separate shell instead." >&2
  exit 1
fi

# Ensure the `ant` CLI is installed on the poller host.
if ! command -v ant >/dev/null 2>&1; then
  echo "Installing ant CLI..."
  VERSION="${ANT_VERSION:-1.15.0}"
  OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
  case "$(uname -m)" in
    x86_64) ARCH=amd64 ;;
    aarch64|arm64) ARCH=arm64 ;;
    *) echo "Unsupported arch $(uname -m)" >&2; exit 1 ;;
  esac
  SUDO=""; [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1 && SUDO="sudo"
  curl -fsSL "https://github.com/anthropics/anthropic-cli/releases/download/v${VERSION}/ant_${VERSION}_${OS}_${ARCH}.tar.gz" \
    | $SUDO tar -xz -C /usr/local/bin ant
fi

# Ensure the worker image exists (build the dev base + worker if missing).
IMAGE="${VECTOR_RS_WORKER_IMAGE:-vector-rs-worker}"
if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "Worker image '$IMAGE' not found — building (dev base + worker)..."
  docker build -f "$REPO_ROOT/vector-rs/Dockerfile.dev"    -t vector-rs-dev "$REPO_ROOT"
  docker build -f "$REPO_ROOT/vector-rs/Dockerfile.worker" -t "$IMAGE"      "$REPO_ROOT"
fi

echo "▶ Polling environment $ANTHROPIC_ENVIRONMENT_ID; one $IMAGE container per session."
echo "  Verify from another shell (with your API key): ant beta:environments:work stats --environment-id $ANTHROPIC_ENVIRONMENT_ID"
exec ant beta:worker poll --on-work "$SCRIPT_DIR/spawn.sh"
