"""
Phase 1.3 — CLAP inference parity test (FMA, local audio).

Two-level check on 50 FMA tracks that already have a stored production `v_clap`:

  Level 1 (reimplementation): local MPS embedding vs local CPU embedding on the same audio.
      Expect cosine ~= 1.0. Validates the port and quantifies MPS-vs-CPU float drift
      (production forced CPU). If MPS drifts > tolerance vs CPU, embed on CPU instead.

  Level 2 (vs production): local embedding vs the stored `v_clap`. Target cosine >= 0.999.
      Confirms our preprocessing matches whatever produced the stored vectors.

Audio is the exact file named by each track's `relative_path`, rooted at the external drive
(`/Volumes/Samsung/Projects/cloud-crate/`), so we compare against the same source production used.

Also reports MPS throughput (tracks/min) to decide whether an MLX port is warranted.

Usage:
    uv run python -m src.parity                 # 50 tracks, default paths
    uv run python -m src.parity --n 100
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import duckdb
import numpy as np

from src.clap_common import CHECKPOINT, REVISION
from src.embed import embed_files

FINETUNE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT = FINETUNE_ROOT / "data" / "snapshot"
LIBRARY_ROOT = Path("/Volumes/Samsung/Projects/cloud-crate")
PARITY_TARGET = 0.999  # level 2: local vs stored
MPS_DRIFT_TARGET = 0.999  # level 1: mps vs cpu
# The FMA corpus is 30 s clips embedded from their 10-20 s window (offset=10), not the
# library's offset=30 (which skips intros of full-length songs). Verified empirically:
# offset=10 reproduces the stored FMA v_clap at cosine 1.00000.
FMA_OFFSET = 10.0


def _latest_snapshot(snapshot_dir: Path) -> Path:
    matches = sorted(snapshot_dir.glob("tracks_clap_*.parquet"))
    if not matches:
        raise FileNotFoundError(f"No snapshot under {snapshot_dir}")
    return matches[-1]


def _cos(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def select_tracks(snapshot: Path, n: int) -> list[tuple[str, str, np.ndarray]]:
    """Deterministically pick n FMA tracks with non-zero v_clap whose audio resolves locally."""
    con = duckdb.connect()
    rows = con.execute(
        """
        SELECT id, relative_path, v_clap
        FROM read_parquet(?)
        WHERE source = 'fma'
          AND list_dot_product(v_clap, v_clap) > 1e-6
        ORDER BY id
        """,
        [str(snapshot)],
    ).fetchall()
    con.close()
    selected = []
    for tid, rel, vclap in rows:
        path = LIBRARY_ROOT / rel
        if path.exists():
            selected.append((tid, str(path), np.asarray(vclap, dtype=np.float32)))
        if len(selected) >= n:
            break
    return selected


def run(snapshot: Path, n: int) -> dict:
    tracks = select_tracks(snapshot, n)
    if not tracks:
        raise RuntimeError(f"No FMA audio resolved under {LIBRARY_ROOT} — is the drive mounted?")
    paths = [p for _id, p, _v in tracks]
    stored = {p: v for _id, p, v in tracks}
    print(f"Selected {len(tracks)} FMA tracks with stored v_clap + local audio.")

    # MPS pass (timed for throughput). FMA_OFFSET matches how the stored FMA vectors were made.
    t0 = time.perf_counter()
    mps_vecs = embed_files(paths, device_str="mps", batch_size=4, offset=FMA_OFFSET)
    mps_secs = time.perf_counter() - t0
    # CPU pass (reference).
    cpu_vecs = embed_files(paths, device_str="cpu", batch_size=4, offset=FMA_OFFSET)

    per_track = []
    for p in paths:
        if p not in mps_vecs or p not in cpu_vecs:
            continue  # skipped (too short after offset)
        m, c, s = mps_vecs[p], cpu_vecs[p], stored[p]
        per_track.append(
            {
                "path": p,
                "cos_mps_vs_stored": round(_cos(m, s), 6),
                "cos_cpu_vs_stored": round(_cos(c, s), 6),
                "cos_mps_vs_cpu": round(_cos(m, c), 6),
            }
        )

    def _stats(key: str) -> dict:
        vals = [t[key] for t in per_track]
        return {"min": round(min(vals), 6), "mean": round(sum(vals) / len(vals), 6)}

    n_embedded = len(per_track)
    throughput = round(n_embedded / mps_secs * 60, 1) if mps_secs else 0.0
    # realtime factor: each embed consumes a 10 s window, so audio-seconds = n * 10.
    realtime_x = round((n_embedded * 10) / mps_secs, 1) if mps_secs else 0.0

    summary = {
        "checkpoint": CHECKPOINT,
        "hf_revision": REVISION,
        "n_selected": len(tracks),
        "n_embedded": n_embedded,
        "level2_mps_vs_stored": _stats("cos_mps_vs_stored"),
        "level2_cpu_vs_stored": _stats("cos_cpu_vs_stored"),
        "level1_mps_vs_cpu": _stats("cos_mps_vs_cpu"),
        "parity_target": PARITY_TARGET,
        "mps": {
            "seconds": round(mps_secs, 2),
            "tracks_per_min": throughput,
            "realtime_factor": realtime_x,
        },
    }

    l2 = summary["level2_mps_vs_stored"]
    l2c = summary["level2_cpu_vs_stored"]
    l1 = summary["level1_mps_vs_cpu"]
    print("\n=== Parity results ===")
    print(f"Level 2  MPS vs stored : min={l2['min']:.6f} mean={l2['mean']:.6f}  (target >= {PARITY_TARGET})")
    print(f"Level 2  CPU vs stored : min={l2c['min']:.6f} mean={l2c['mean']:.6f}")
    print(f"Level 1  MPS vs CPU    : min={l1['min']:.6f} mean={l1['mean']:.6f}  (target >= {MPS_DRIFT_TARGET})")
    print(f"MPS throughput         : {throughput} tracks/min  ({realtime_x}x realtime)")

    l2_pass = l2["min"] >= PARITY_TARGET
    l1_pass = l1["min"] >= MPS_DRIFT_TARGET
    summary["level2_pass"] = l2_pass
    summary["level1_pass"] = l1_pass
    print(f"\nLevel 2 (production parity): {'PASS' if l2_pass else 'FAIL'}")
    print(f"Level 1 (MPS==CPU):          {'PASS' if l1_pass else 'FAIL — embed on CPU'}")

    out = FINETUNE_ROOT / "results" / "parity.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "per_track": per_track}, indent=2))
    print(f"\nWrote {out}")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="CLAP MPS/CPU/stored parity test on FMA tracks.")
    ap.add_argument("--snapshot", type=Path, default=None)
    ap.add_argument("--n", type=int, default=50)
    args = ap.parse_args()
    snapshot = args.snapshot or _latest_snapshot(DEFAULT_SNAPSHOT)
    run(snapshot, args.n)


if __name__ == "__main__":
    main()
