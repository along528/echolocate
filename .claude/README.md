# Claude Code configuration for echolocate

## SessionStart hook

`.claude/hooks/session-start.sh` (registered in `.claude/settings.json`) runs
`vector-rs/scripts/setup-dev.sh` on every **Claude Code on the web** session so
it boots ready to build/run/query vector-rs. It is a no-op for local CLI
sessions (gated on `CLAUDE_CODE_REMOTE`). Full context:
[`vector-rs/README.md` § Dev Sandbox](../vector-rs/README.md#dev-sandbox-remote--interactive-development);
per-script timing/ownership in
[`vector-rs/scripts/README.md`](../vector-rs/scripts/README.md).

The hook takes effect for future sessions **once this is on the default branch**.

## One-time environment setup (network policy)

The hook downloads native dependencies, so the web environment's **network
policy must allow the hosts below** — otherwise sessions start but can't compile
or run vector-rs (the hook reports the blocked host and degrades gracefully).
Pick/adjust the policy when creating the environment
([Claude Code on the web docs](https://code.claude.com/docs/en/claude-code-on-the-web)):

- [ ] **`storage.googleapis.com`** — libduckdb, onnxruntime, `vss`, and the
      CLAP model — all public objects, no credentials needed — from
      `gs://cloud-crate-vector-db/dev-artifacts/`. `setup-dev.sh` tries this
      **first** for all four. **Required to compile** once a maintainer has
      run `publish-dev-artifacts.sh` (below); the server (semantic search)
      also needs it for the CLAP model.
- [ ] **`github.com` + `objects.githubusercontent.com`** — fallback for
      libduckdb, `onnxruntime`, and the `duckdb` CLI when GCS has no mirror,
      plus the `ant` CLI (release assets). **Cannot be relied on alone**: see
      the cross-owner note below.
- [ ] **`extensions.duckdb.org`** — fallback for the DuckDB `vss` extension
      (runtime `LOAD vss`) when GCS has no mirror.
- [x] **`pypi.org` + `files.pythonhosted.org`** — usually already allowed;
      `duckdb` Python for regenerating the sample index.

### Why GCS, not just `github.com`

Claude Code on the web scopes a session's `github.com` access to a single
repo owner, not just to the host. A session tied to this project can reach
`github.com/along528/*` but **not** `github.com/duckdb/duckdb` or
`github.com/microsoft/onnxruntime` — those 403 unconditionally, and the
`add_repo` tool can't widen this (cross-tier / cross-owner adds are
rejected); the same sessions frequently can't reach `extensions.duckdb.org`
either. Allowlisting `github.com` in the network policy does not fix the
GitHub case. `storage.googleapis.com` has no such per-owner scoping, so it's
the reliable path once the artifacts are mirrored there.

All four native deps (libduckdb, onnxruntime, `vss`, CLAP — one REQUIRED to
build, the rest to run) are published as **public** objects
(`--predefined-acl=publicRead` on each, in `publish-dev-artifacts.sh`) and
fetched with plain `curl` — no `gcloud`, no ADC, so it works even in a
sandbox that doesn't have `gcloud` installed at all (as several already
didn't). This is safe because all four are unmodified re-exports/rebuilds of
public open-source artifacts, not project data (libduckdb/onnxruntime are
upstream release binaries, `vss` is the public DuckDB extension, and the CLAP
model is a stock export of the public `laion/clap-htsat-unfused` HuggingFace
checkpoint — see `vector-rs/scripts/export_clap_text.py`). This bucket also serves the
private audio corpus vector-rs streams in production — only these four
dev-artifacts objects are public, never the bucket itself.

### If the policy can't be widened

- **`storage.googleapis.com` reachable, but the bucket hasn't been seeded** →
  a maintainer runs
  [`vector-rs/scripts/publish-dev-artifacts.sh`](../vector-rs/scripts/publish-dev-artifacts.sh)
  once (needs `roles/storage.objectAdmin` on the bucket) to mirror libduckdb,
  onnxruntime, `vss`, and the CLAP model; after that, no other host — and no
  ADC — is needed to build/run.
- **`storage.googleapis.com` blocked too** → you can't provision natively in
  that session. Use the prebuilt dev container (`vector-rs/Dockerfile.dev`) as
  the environment's base image instead, since it bakes every dependency at
  image-build time (its own Docker build network isn't subject to the
  cross-owner `github.com` restriction).
