# Claude Code configuration for echolocate

## SessionStart hook

`.claude/hooks/session-start.sh` (registered in `.claude/settings.json`) runs
`vector-rs/scripts/setup-dev.sh` on every **Claude Code on the web** session so
it boots ready to build/run/query vector-rs. It is a no-op for local CLI
sessions (gated on `CLAUDE_CODE_REMOTE`). Full context:
[`vector-rs/README.md` § Dev Sandbox](../vector-rs/README.md#dev-sandbox-remote--interactive-development).

The hook takes effect for future sessions **once this is on the default branch**.

## One-time environment setup (network policy)

The hook downloads native dependencies, so the web environment's **network
policy must allow the hosts below** — otherwise sessions start but can't compile
or run vector-rs (the hook reports the blocked host and degrades gracefully).
Pick/adjust the policy when creating the environment
([Claude Code on the web docs](https://code.claude.com/docs/en/claude-code-on-the-web)):

- [ ] **`github.com` + `objects.githubusercontent.com`** — `libduckdb`,
      `onnxruntime`, the `duckdb` CLI, and the `ant` CLI (release assets).
      **Required to compile** — no workaround short of a prebuilt image.
- [ ] **`extensions.duckdb.org`** — the DuckDB `vss` extension (runtime
      `LOAD vss`). Avoidable by publishing `vss` to GCS (below).
- [ ] **`storage.googleapis.com`** — CLAP model (+ optional `vss`) from
      `gs://cloud-crate-vector-db/dev-artifacts/`. Needed to run the **server**
      (semantic search); not needed for `cargo build`/`cargo test`.
- [x] **`pypi.org` + `files.pythonhosted.org`** — usually already allowed;
      `duckdb` Python for regenerating the sample index.

### If the policy can't be widened

- **Only `storage.googleapis.com` blocked** → publish the CLAP model + `vss` to
  the GCS `dev-artifacts/` prefix with
  [`vector-rs/scripts/publish-dev-artifacts.sh`](../vector-rs/scripts/publish-dev-artifacts.sh);
  then the runtime deps come from GCS instead of `extensions.duckdb.org`.
- **`github.com` blocked** → you can't provision natively in that session. Use
  the prebuilt dev container (`vector-rs/Dockerfile.dev`) as the environment's
  base image instead, since it bakes every dependency at image-build time.
