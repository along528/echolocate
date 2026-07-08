# vector-rs as a Managed Agents self-hosted sandbox

Run agents against vector-rs inside infrastructure **you** control, using
Anthropic [Managed Agents](https://www.anthropic.com/engineering/managed-agents).
Managed Agents splits the *brain* (Claude + the agent harness, orchestrated by
Anthropic's control plane) from the *hands* (tool execution). With a **self-hosted
sandbox**, the hands run here: every `bash`/`read`/`write`/`edit`/`glob`/`grep`
tool call the agent makes executes inside a vector-rs worker container that
already has the Rust toolchain, native libs, CLAP model, and the sample index —
so the agent can build, `cargo test`, run the Axum server, and query it, without
the code or filesystem ever leaving your host.

This is the sanctioned way to "point an agent at the vector-rs sandbox": you run
a poller locally, Anthropic drives the session, and the work happens in your
container.

```
                Anthropic control plane                 Your Docker host
        ┌──────────────────────────────┐        ┌──────────────────────────────┐
        │ Claude + harness (the brain) │        │  run-worker.sh                │
        │  • runs the model            │  work  │   └ ant beta:worker poll      │
        │  • decides tool calls        │ queue  │       └ spawn.sh (per session)│
        │  • self_hosted environment   │◀──────▶│           └ docker run        │
        └──────────────────────────────┘ results│               vector-rs-worker│
                                                 │   (bash/cargo/curl in here)   │
                                                 └──────────────────────────────┘
```

## Terminology

| Term | What it is |
|------|------------|
| **Environment** (`type: self_hosted`) | The queue your worker polls. Has an ID `env_…`. |
| **Environment key** (`sk-ant-oat01-…`) | Console-generated. Authenticates the **worker** to its queue. Lives only on the worker host / in the container. |
| **Org API key** (`ANTHROPIC_API_KEY`) | Creates sessions and reads stats. Used **only off-host** — never on the worker (it would be exposed to agent tool calls). |
| **Agent** | The configured brain (model, e.g. Claude Opus 4.8, + system prompt). Has an agent ID. |
| **Session** | One agent run, targeted at an environment; enqueued as a **work item**. |
| **Worker** | `ant beta:worker` — claims work, downloads skills, runs tools, posts results. |

## One-time setup

You need the [`ant` CLI](https://platform.claude.com/docs/en/managed-agents/self-hosted-sandboxes)
(or an Anthropic SDK) and an `ANTHROPIC_API_KEY` **on your workstation** (not the
worker host, if they differ).

1. **Create the self-hosted environment** and note the `env_…` ID:
   ```bash
   ant beta:environments create --name vector-rs --config '{"type":"self_hosted"}'
   ```
2. **Generate the environment key** in the [Console](https://platform.claude.com/workspaces/default/environments)
   (open the environment → *Generate environment key*). Key generation is
   Console-only.
3. **Create an agent** (choose the model, e.g. Claude Opus 4.8) and note its ID —
   see the [agent setup docs](https://platform.claude.com/docs/en/managed-agents/agent-setup).
   Give it a system prompt oriented at vector-rs, e.g. *"You develop the vector-rs
   Rust service. The checkout is at /workspace; build with `cd vector-rs && cargo
   build`, test with `cargo test`, and run the server against the committed sample
   index (`INDEX_DB_PATH=/opt/vector-rs/sample_index.duckdb`). Write deliverables
   to /mnt/session/outputs."*

## Run the worker

On the Docker host (your laptop or a VM):

```bash
export ANTHROPIC_ENVIRONMENT_ID=env_...
export ANTHROPIC_ENVIRONMENT_KEY=sk-ant-oat01-...
unset ANTHROPIC_API_KEY            # must not be present on the worker host

bash vector-rs/scripts/run-worker.sh
```

`run-worker.sh` installs `ant` if needed, builds the worker image
(`Dockerfile.dev` → `Dockerfile.worker`) on first run, then polls the queue.
For each session it runs `scripts/spawn.sh`, which launches one fresh
`vector-rs-worker` container with the session's identifiers, the repo mounted at
`/workspace`, and a host outputs dir bind-mounted at `/mnt/session/outputs`.

Verify the worker is connected — from **another shell, with your API key**:

```bash
ant beta:environments:work stats --environment-id "$ANTHROPIC_ENVIRONMENT_ID"
# expect workers_polling >= 1
```

## Start a session

From your workstation (API key), target the environment:

```bash
ant beta:sessions create \
  --agent "$AGENT_ID" \
  --environment-id "$ANTHROPIC_ENVIRONMENT_ID" \
  --metadata '{"commit":"<sha>"}' \
  --message "Run cargo test, then start the server and curl /search?q=blue&source=library. Summarize results to /mnt/session/outputs/report.md."
```

The session enters the queue; your poller claims it, spawns a container, and the
agent works inside it. Deliverables appear under
`/tmp/vector-rs-sessions/<session-id>/` on the host (configurable via
`OUTPUTS_ROOT`).

## Pinning a commit

Managed Agents does **not** auto-mount repos into self-hosted sandboxes. By
default `spawn.sh` bind-mounts your working copy at `/workspace` (fast, for local
dev). For reproducible runs, pass the target commit in the session
`--metadata '{"commit":"<sha>"}'` and, before launching the container, check that
SHA out into a temp dir and point `spawn.sh` at it:

```bash
# inside a customized --on-work handler, per claimed work item:
git -C /tmp/vrs-$SHA ... worktree/checkout "$SHA"
REPO_MOUNT=/tmp/vrs-$SHA   # spawn.sh mounts this at /workspace
```

The claimed work item (and its `metadata`) is available through the
[Environments Work endpoints](https://platform.claude.com/docs/en/api/beta/environments/work)
or the SDK work poller if you want a fully programmatic handler instead of the
shell `spawn.sh`.

## Credential boundary (important)

- The **environment key** is the only Anthropic credential inside the container.
  `spawn.sh` forwards `ANTHROPIC_SESSION_ID/WORK_ID/ENVIRONMENT_ID/ENVIRONMENT_KEY`
  and nothing else.
- **Never** set `ANTHROPIC_API_KEY` on the worker host — `run-worker.sh` refuses
  to start if it is set. Run `sessions create` / `work stats` / `work stop` from
  a separate machine or shell.

## Ops

```bash
# queue depth + liveness (API key, off-host)
ant beta:environments:work stats --environment-id "$ANTHROPIC_ENVIRONMENT_ID"

# stop a session gracefully
ant beta:environments:work stop --environment-id "$ANTHROPIC_ENVIRONMENT_ID" --work-id "$WORK_ID"
```

## CI autofix (example)

A worked example of triggering a session from a **failed CI build**, letting the
agent fix + validate it in the sandbox, and opening a PR with the patch —
honoring the brain/hands split end to end — is in
[`autofix.md`](autofix.md) (opt-in; inert until enabled).

## Scaling up

The generic Docker-host poller here is the reference path. To run this at scale
with pre-warmed pods, gVisor isolation, and egress lockdown, the **same worker
image** drops into the GKE Agent Sandbox — see [`gke/README.md`](gke/README.md).
