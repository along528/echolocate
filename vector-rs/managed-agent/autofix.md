# CI autofix via Managed Agents (example)

An opt-in loop: when `vector-rs-ci` fails, a Managed Agents session diagnoses and
fixes the break **in the worker sandbox**, then a trusted step opens a PR with the
validated patch. It's a direct application of the brain/hands split — the failing
logs, the fix reasoning, and the validated diff all cross the work-queue boundary
rather than living in one process.

| Stage | BRAIN (Anthropic) | HANDS (your container) | TRUSTED glue (the Action) |
|-------|-------------------|------------------------|---------------------------|
| Trigger | — | — | `workflow_run` on `vector-rs-ci` failure |
| Propose | reasons about the failure | — | creates the session (API key, this step only) |
| Validate | decides "run `cargo test`", reads output | **runs `cargo test` in-sandbox**, iterates | — |
| Apply | writes `fix.patch` via a write tool | patch lands on container FS → host outputs | `git apply` + open PR (GITHUB_TOKEN only) |

The agent **never** holds repo-write or org credentials. Its fix is validated
in-sandbox before the patch is surfaced, and the resulting PR re-runs normal CI
and waits for human review — no auto-merge.

## Three variants (pick one)

| Variant | Where the hands run | When to use |
|---------|---------------------|-------------|
| **gh-aw on a self-hosted runner** (recommended) | your self-hosted GitHub runner, backed by the vector-rs sandbox image | GitHub-native CI autofix that stays in your infra, with minimal code |
| Managed Agents worker | your container via the work queue | agents on vector-rs triggered from anywhere (not just CI), strict VPC/egress boundary |
| Raw Actions workflow | ephemeral GitHub runner + the `ant` worker | quick illustration / no self-hosted runner yet |

### Recommended: gh-aw + self-hosted runner
[`.github/workflows/vector-rs-autofix.md`](../../.github/workflows/vector-rs-autofix.md)
is a [GitHub Agentic Workflow](https://github.github.com/gh-aw/): a markdown
workflow (`engine: claude`) whose agent runs **read-only** and opens the PR via a
sanitized `safe-outputs: create-pull-request` — so gh-aw provides the guardrails
(no repo-write creds to the agent, PR-not-push) natively. Point it at a
`runs-on: [self-hosted, vector-rs]` runner backed by `Dockerfile.dev` (or one that
runs `setup-dev.sh`) and tool execution stays in your infra. Compile + run:
```bash
gh extension install github/gh-aw
gh aw compile          # emits .github/workflows/vector-rs-autofix.lock.yml (commit it)
```
Needs repo secret `ANTHROPIC_API_KEY`. gh-aw is in technical preview — verify the
frontmatter against the current docs before compiling.

### Files
- [`.github/workflows/vector-rs-autofix.md`](../../.github/workflows/vector-rs-autofix.md) — gh-aw source (recommended). Inert until `gh aw compile`.
- [`examples/vector-rs-autofix.yml`](examples/vector-rs-autofix.yml) — the raw Actions fallback (moved out of `.github/workflows/` so it doesn't run). Uses `spawn.sh` + `apply-agent-patch.sh` instead of safe-outputs.
- [`../scripts/spawn.sh`](../scripts/spawn.sh) — per-session container (Managed Agents worker + raw fallback).
- [`../scripts/apply-agent-patch.sh`](../scripts/apply-agent-patch.sh) — trusted apply/open-PR step for the raw/worker paths (also handy locally).

## Agent contract
Configure the autofix agent's system prompt to:
> Read `/workspace/.autofix/ci-failure.log`. Fix the vector-rs build. Validate by
> running `cd vector-rs && cargo test` until it passes. Write the change as a
> single git diff to `/mnt/session/outputs/fix.patch`. Make no other changes.

## Test locally BEFORE merging

The whole loop runs on your laptop without GitHub Actions — this is the best
pre-merge validation. Needs Docker + an Anthropic API key with the Managed Agents
beta.

1. **One-time**: create the `self_hosted` environment + environment key + the
   autofix agent (see [`README.md`](README.md)); `export ANTHROPIC_ENVIRONMENT_ID`
   / `ANTHROPIC_ENVIRONMENT_KEY`.
2. **Build the worker image**:
   ```bash
   docker build -f vector-rs/Dockerfile.dev    -t vector-rs-dev    .
   docker build -f vector-rs/Dockerfile.worker -t vector-rs-worker .
   ```
3. **Break the build on purpose** on a scratch branch (e.g. a type error in
   `vector-rs/src/handlers/search.rs`); commit; note the SHA. Stage a log the
   agent can read: `mkdir -p .autofix && cargo build 2> .autofix/ci-failure.log || true`.
4. **Run the worker poller** (hands): `bash vector-rs/scripts/run-worker.sh`.
5. **Create a session** (brain; separate shell, API key set):
   ```bash
   ant beta:sessions create --agent "$AGENT_ID" \
     --environment-id "$ANTHROPIC_ENVIRONMENT_ID" \
     --metadata '{"task":"fix_ci","logs":".autofix/ci-failure.log"}'
   ```
6. **Watch**: `spawn.sh` launches a `vector-rs-worker` container; the agent edits
   + `cargo test`s inside it; a diff appears at
   `/tmp/vector-rs-sessions/<session>/fix.patch`.
7. **Apply locally** (no push): `OUTPUTS_ROOT=/tmp/vector-rs-sessions bash
   vector-rs/scripts/apply-agent-patch.sh` → applies to a branch for you to inspect.

Smaller pieces you can test with **no** Anthropic setup:
- `apply-agent-patch.sh` against a hand-written `fix.patch` (mechanism only).
- `docker run --rm vector-rs-worker ant --version` (image + entrypoint).

## Activate AFTER merging

**Recommended (gh-aw + self-hosted runner):**
1. Register a **self-hosted runner** labelled `vector-rs`, backed by the
   `Dockerfile.dev` image (or running `setup-dev.sh` on startup). Keep fork PRs
   off self-hosted runners.
2. Add repo secret `ANTHROPIC_API_KEY`.
3. `gh aw compile` and commit `vector-rs-autofix.lock.yml`.
4. Push a deliberately-broken vector-rs commit → confirm an `autofix:` PR opens
   with a validated fix and re-runs normal CI.

**Raw Actions fallback** (`examples/vector-rs-autofix.yml`, if you don't have a
self-hosted runner): move it back into `.github/workflows/`, then also:
1. **Publish the worker image** to a registry the runner can pull (reuse the
   `cloudbuild.yaml` pattern to build + push `Dockerfile.worker`); set repo var
   `VECTOR_RS_WORKER_IMAGE`.
2. **Repo secrets**: `ANTHROPIC_API_KEY`, `ANTHROPIC_ENVIRONMENT_ID`,
   `ANTHROPIC_ENVIRONMENT_KEY`, `AUTOFIX_AGENT_ID`.
3. **Repo var** `VECTOR_RS_AUTOFIX_ENABLED=true`.

## Known limits (be honest about these)
- The sandbox uses the **synthetic sample index**, so it validates compile +
  tests + API shape, not real-corpus behavior.
- The in-Action worker `docker pull`s the image each run; a persistent poller or
  the GKE Agent Sandbox ([`gke/README.md`](gke/README.md)) avoids that.
- Bound the agent (max iterations / cost) and keep human review in the loop.
