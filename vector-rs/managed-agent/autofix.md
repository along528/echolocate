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

## Files
- [`.github/workflows/vector-rs-autofix.yml`](../../.github/workflows/vector-rs-autofix.yml) — the workflow (inert until enabled).
- [`../scripts/spawn.sh`](../scripts/spawn.sh) — per-session container (reused).
- [`../scripts/apply-agent-patch.sh`](../scripts/apply-agent-patch.sh) — the trusted apply/open-PR step (also runs locally).

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
`workflow_run` workflows only fire from the default branch, so nothing happens
until this is on `main` **and**:
1. **Publish the worker image** to a registry the runner can pull (reuse the
   `cloudbuild.yaml` pattern to build + push `Dockerfile.worker`); set repo var
   `VECTOR_RS_WORKER_IMAGE`.
2. **Repo secrets**: `ANTHROPIC_API_KEY`, `ANTHROPIC_ENVIRONMENT_ID`,
   `ANTHROPIC_ENVIRONMENT_KEY`, `AUTOFIX_AGENT_ID`.
3. **Repo var** `VECTOR_RS_AUTOFIX_ENABLED=true`.
4. Push a deliberately-broken vector-rs commit → confirm an `autofix/ci-*` PR
   opens with a validated fix and re-runs normal CI.

## Known limits (be honest about these)
- The sandbox uses the **synthetic sample index**, so it validates compile +
  tests + API shape, not real-corpus behavior.
- The in-Action worker `docker pull`s the image each run; a persistent poller or
  the GKE Agent Sandbox ([`gke/README.md`](gke/README.md)) avoids that.
- Bound the agent (max iterations / cost) and keep human review in the loop.
