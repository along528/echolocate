# vector-rs dev-sandbox scripts

These scripts provision and run the vector-rs dev sandbox. This file is about
**when and by whom each one runs**; for the full narrative (substrates, egress
policy, GCS artifacts) see [`vector-rs/README.md` §
Dev Sandbox](../README.md#dev-sandbox-remote--interactive-development) and
[`.claude/README.md`](../../.claude/README.md).

## Who runs what, and when

| Script | Purpose | Who runs it | Trigger / when | Frequency | Prerequisites |
|--------|---------|-------------|----------------|-----------|---------------|
| [`setup-dev.sh`](setup-dev.sh) | Provision native deps + build toolchain (build/test/run/query) | The SessionStart hook (web), or a dev by hand | Automatically on **Claude Code on the web** session start; or manually on a laptop/container | Once per fresh environment (idempotent — cheap no-op after) | `apt`; egress to GCS (tried first for everything — libduckdb/onnxruntime need no auth, vss/CLAP need ADC) and, as fallback, github.com / extensions.duckdb.org |
| [`dev-env.sh`](dev-env.sh) | Export the build/run env vars (`DUCKDB_LIB_DIR`, `ORT_DYLIB_PATH`, `INDEX_DB_PATH`, …) | Interactive shells | **Sourced, not executed** — auto-sourced via `~/.bashrc` (wired by `setup-dev.sh`); or `source scripts/dev-env.sh` by hand before `cargo run` | Every shell | `setup-dev.sh` has run (or the libs are otherwise present) |
| [`publish-dev-artifacts.sh`](publish-dev-artifacts.sh) | Seed GCS `dev-artifacts/` with libduckdb + onnxruntime (uploaded **public**, `--predefined-acl=publicRead`, so `setup-dev.sh` needs no ADC for them) and the CLAP model + vss extension (private, ADC-gated) so `setup-dev.sh` can fetch all four from GCS instead of `github.com/duckdb/duckdb`, `github.com/microsoft/onnxruntime`, torch-exporting, or hitting the extension repo — the first two matter beyond convenience since Claude Code on the web blocks those cross-owner `github.com` repos unconditionally (see [`../README.md`](../README.md#egress-requirements)). Only those two objects are public; never widen this to the whole bucket, which also serves the private audio corpus | A maintainer | **One-time / rare** — run once, and again only when a pinned version (libduckdb, onnxruntime) or the CLAP model / vss extension changes | Rare | `gcloud` authed with `roles/storage.objectAdmin` on `gs://cloud-crate-vector-db`; egress to github.com (to fetch libduckdb/onnxruntime for re-upload) |
| [`../Dockerfile.dev`](../Dockerfile.dev) | Image-build-time alternative to `setup-dev.sh` — bakes every dep (+ CLAP + sample) into a reusable dev image | Whoever builds the devcontainer image | At **image build** (`docker build -f Dockerfile.dev`) | When the image needs rebuilding | Docker |
| [`../../embeddings/generate_sample_index.py`](../../embeddings/generate_sample_index.py) | Produce the committed `testdata/sample_index.duckdb` (tiny synthetic stand-in with the baked-index schema + HNSW indexes) | A maintainer | **Rare** — only when the index schema changes or a realistic subset is wanted | Rare | duckdb **pinned to `~=1.2.0`** + numpy; vss reachable (for HNSW) |

## Lifecycle / dependency chain

```
generate_sample_index.py ──(commit)──► testdata/sample_index.duckdb ────────┐
publish-dev-artifacts.sh ──(once)─────► GCS dev-artifacts/ (libduckdb+ort+  ┤
                                          CLAP+vss)                         ▼
web session start ─► .claude/hooks/session-start.sh ─► setup-dev.sh
      ─► (fetch GCS, fall back to github/extensions.duckdb.org) ─► dev-env.sh sourced ─► cargo build / run / test
```

## Gotcha: the SessionStart hook only activates after merge to `main`

`session-start.sh` is registered in `.claude/settings.json`, but Claude Code
loads hook config from the **default branch**. So the automatic provisioning
does not run in web sessions until this work is merged to `main`. Until then,
exercise the sandbox manually: build `Dockerfile.dev`, or run `setup-dev.sh` by
hand. `session-start.sh` is also a **no-op for local CLI sessions** — it's gated
on `CLAUDE_CODE_REMOTE=true`.

## Now vs. after merge

- **`publish-dev-artifacts.sh`** is decoupled from the merge — the hook only
  needs the artifacts to already exist whenever it eventually runs. Run it
  **whenever** you have bucket write access; there's no reason to wait for merge.
- **`generate_sample_index.py`** only needs re-running when the schema changes.
  Do it **before merge** (so the PR ships the intended sample) and **pin duckdb
  to `~=1.2.0`** — a sample written by a newer duckdb may embed a vss/HNSW index
  format the runtime's libduckdb 1.2.x can't use. The script warns if the
  installed duckdb differs from the 1.2.x series.
