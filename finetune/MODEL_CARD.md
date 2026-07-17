# CLAP model card — production parity reference

The exact model + preprocessing that produced the production `v_clap` embeddings, and that
`src/embed.py` reproduces locally. Constants live in `src/clap_common.py`.

## Checkpoint

| | |
|---|---|
| Repo | `laion/clap-htsat-unfused` |
| Pinned revision | `8fa0f1c6d0433df6e97c127f64b2a1d6c0dcda8a` |
| Revision last modified | 2023-04-24 |
| Library | `transformers==4.46.0` (`ClapModel`, `AutoProcessor`) |
| Embedding dim | 512 |

**Revision caveat.** The production pipeline (`embeddings/generate_clap.py`, `vector-rs/scripts/export_clap_text.py`)
calls `from_pretrained` with **no `revision=`**, so it floated on whatever `main` served at
download time. We pin the revision above for reproducibility. Its safety rests on the fact that
the checkpoint's `main` has not changed since 2023-04-24 — well before this project generated
any embeddings — so this revision is (to very high confidence) the one the stored `v_clap`
vectors were produced from. The Phase 1 parity test confirms this empirically.

## Audio preprocessing (produces `v_clap`)

Identical to `embeddings/generate_clap.py`:

| param | value |
|---|---|
| Sample rate | 48000 Hz |
| Window duration | 10 s |
| Offset | **30 s (library)** / **10 s (FMA)** — see note |
| Channels | mono (`librosa.load` default downmix) |
| Loader | `librosa.load(path, sr=48000, duration=10, offset=30)` |
| Min length | skip if < 1 s remains after offset |
| Feature extractor | `laion/clap-htsat-unfused` `preprocessor_config.json` (HTSAT: 64 mel bins, fusion off) — carried by `AutoProcessor`, not repo code; pinned via `revision` |
| Forward | `ClapModel.get_audio_features(**inputs)` |
| Post | explicit L2 normalization to unit length |

Single window per track (no multi-chunk aggregation). Stored as `FLOAT[512]`.

**Offset differs by corpus.** `generate_clap.py`'s default is `offset=30`, used for the
full-length personal library (skips intros). The FMA corpus is 30 s clips, so `offset=30`
would yield nothing — its stored vectors were made from the **10-20 s window (`offset=10`)**.
Verified empirically: `offset=10` reproduces a stored FMA `v_clap` at cosine `1.00000` on CPU;
`offset=0`/`5`/full-clip do not (0.923 / 0.990 / 0.966). `src/embed.py` takes `offset` as a
parameter defaulting to 30; `src/parity.py` passes 10 for FMA.

## Parity results (Phase 1.3, 2026-07-14)

50 FMA tracks, local audio, `offset=10`. Full results in `results/parity.json`.

| comparison | min cos | mean cos | target | verdict |
|---|---|---|---|---|
| MPS vs stored production | 0.999695 | 0.999977 | ≥ 0.999 | **PASS** |
| CPU vs stored production | 0.999764 | 0.999981 | — | reference |
| MPS vs CPU (port + drift) | 0.999695 | 0.999979 | ≥ 0.999 | **PASS** |

MPS throughput: **532.8 tracks/min (88.8× realtime)** — far above the ~5× threshold, so we stay
on MPS/PyTorch (no MLX port needed). MPS requires `PYTORCH_ENABLE_MPS_FALLBACK=1` because the
audio encoder's bicubic upsample (`reshape_mel2img`) is unimplemented on MPS in torch 2.2.2;
that op falls back to CPU (set automatically in `src/clap_common.py`). The tiny MPS-vs-CPU drift
(min 0.9997) is well within tolerance.

## Text encoding (query side, for eval)

Same checkpoint/revision. `ClapModel.get_text_features(**inputs)` followed by explicit L2
normalization — numerically equivalent to the production ONNX text encoder
(`vector-rs/scripts/export_clap_text.py`, which self-verifies torch↔ONNX max-abs-diff < 1e-4). Neither
`get_text_features` nor `get_audio_features` normalizes internally; we add it on both sides so
cosine == dot.

## Device

Production forced CPU (`generate_clap.py` comment: "stability on Intel MBP"). Locally we allow
MPS for throughput; the Phase 1 parity test quantifies MPS-vs-CPU float drift and falls back to
CPU if it exceeds tolerance.
