---
# GitHub Agentic Workflow (gh-aw, technical preview) — CI autofix for vector-rs.
#
# This is the recommended form of the autofix loop: a markdown workflow whose
# agent runs on YOUR self-hosted runner (tool execution stays in your infra —
# the brain/hands split, GitHub-native) and opens a PR via a sanitized safe
# output (the agent itself has read-only perms and no repo-write creds).
#
# It is a SOURCE file: compile it into a runnable Actions workflow with
#   gh extension install github/gh-aw
#   gh aw compile            # emits .github/workflows/vector-rs-autofix.lock.yml
# then commit the generated .lock.yml. A bare .md in .github/workflows/ is inert
# until compiled, so this is safe to merge. gh-aw is in technical preview — verify
# these frontmatter fields against https://github.github.com/gh-aw/ before compiling.
#
# Requires: repo secret ANTHROPIC_API_KEY (the `claude` engine), and a self-hosted
# runner labelled `vector-rs` backed by the vector-rs sandbox image
# (vector-rs/Dockerfile.dev) or one that runs vector-rs/scripts/setup-dev.sh.

on:
  workflow_run:
    workflows: ["vector-rs-ci"]
    types: [completed]

# Tool execution runs here → keep it in your infra with a self-hosted runner that
# already has libduckdb / onnxruntime / vss / CLAP + the committed sample index.
runs-on: [self-hosted, vector-rs]

engine: claude

permissions:
  contents: read
  actions: read        # read the failing run's logs

# Agent job is read-only; the proposed change is buffered and a separate,
# permission-scoped job opens the PR. The agent never holds repo-write creds.
safe-outputs:
  create-pull-request:
    title-prefix: "autofix: "
    labels: [autofix, vector-rs]
    draft: true

tools:
  bash: [":*"]         # cargo, git — scoped to the runner

timeout_minutes: 30
---

# Fix the failing vector-rs build

The `vector-rs-ci` workflow just failed (run id `${{ github.event.workflow_run.id }}`,
head `${{ github.event.workflow_run.head_sha }}`).

1. Read the failing job's logs to understand the compile or test error.
2. In `vector-rs/`, make the **smallest** change that fixes it.
3. Validate on this runner: `cd vector-rs && cargo test` must pass. The runner has
   the toolchain and the committed sample index, so tests run for real here.
4. Do not touch unrelated files; keep the diff minimal and focused.

When the tests pass, open a pull request with the fix (create-pull-request safe
output). In the PR body, explain the root cause and why the change fixes it.
