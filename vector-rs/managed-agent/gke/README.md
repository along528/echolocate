# vector-rs Managed Agents worker on GKE Agent Sandbox (scale-up — not yet built)

The [generic Docker-host worker](../README.md) is the reference path and runs
locally today. This directory is a **placeholder** for the production scale-up:
running the *same* `vector-rs-worker` image under the
[GKE Agent Sandbox](https://github.com/GoogleCloudPlatform/kubernetes-engine-samples/tree/main/ai-ml/anthropic-agent-sandbox)
add-on, which is Google's reference implementation of Anthropic's self-hosted
Managed Agents on Kubernetes.

## What it would add over the Docker-host poller

| Concern | Docker host (built) | GKE Agent Sandbox (this dir, TODO) |
|---------|--------------------|------------------------------------|
| Per-session isolation | `docker run` per session | **gVisor**-isolated pod per session |
| Cold start | image already local | **`SandboxWarmPool`** of pre-created pods; **`SandboxClaim`** binds one in <1s |
| Poller | `run-worker.sh` on one host | **dispatcher** Deployment (binds claims, holds only the env key) |
| Autoscaling | manual | **stats-adapter** patches warm-pool size from queue depth |
| Egress control | host network policy | **`FQDNNetworkPolicy`** locked to `api.anthropic.com` |
| Credentials | env key in container | env key in pods; **org API key only in stats-adapter**, never in sandboxes |

## How the pieces map

- **Worker image** — unchanged. `vector-rs/Dockerfile.worker` already installs
  `ant` and uses `ENTRYPOINT ["ant","beta:worker","run"]`, which is exactly the
  `src/worker/` contract the GKE sample expects. Point the sample's warm-pool pod
  spec at this image (push it to Artifact Registry first).
- **Dispatcher / stats-adapter** — taken as-is from the GKE sample; they are
  workload-agnostic (they orchestrate sessions, not vector-rs specifics).
- **Data** — the sample index is baked into the image, so no GCS FUSE / PV is
  needed for dev tasks. For tasks needing the full corpus, mount the real index
  or reach the deployed vector-rs service (subject to the FQDNNetworkPolicy
  escape hatch).

## To build this out later

1. Follow the GKE sample's `make infra` / `make images` / `make deploy` flow.
2. Replace the sample worker image with `vector-rs-worker` in the
   `SandboxWarmPool` pod template.
3. Reuse the `self_hosted` environment + environment key from
   [`../README.md`](../README.md) (the environment is host-agnostic).

Tracked as a follow-up; intentionally no manifests here yet.
