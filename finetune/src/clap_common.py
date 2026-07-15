"""
Shared CLAP model constants + loaders, used by both the Phase 0 text ranker
(`src/eval/score.py`) and the Phase 1 audio embedder (`src/embed.py`).

Mirrors production exactly (`embeddings/generate_clap.py`): checkpoint
`laion/clap-htsat-unfused` via transformers, 48 kHz / 10 s window at 30 s offset / mono,
`get_audio_features` / `get_text_features` followed by an explicit L2 normalization.

The production pipeline pinned no HF revision. We pin one here for reproducibility. The
checkpoint's `main` was last modified 2023-04-24 — well before this project generated any
embeddings — so this revision is the one the stored `v_clap` vectors were produced from.
"""

from __future__ import annotations

import os

# The CLAP audio encoder uses bicubic upsampling (reshape_mel2img), which is unimplemented on
# MPS in torch 2.2.2. Allow those specific ops to fall back to CPU so MPS is usable at all.
# Must be set before torch initializes the MPS backend.
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

import numpy as np  # noqa: E402
import torch  # noqa: E402
from transformers import AutoProcessor, ClapModel  # noqa: E402

CHECKPOINT = "laion/clap-htsat-unfused"
REVISION = "8fa0f1c6d0433df6e97c127f64b2a1d6c0dcda8a"

# Audio preprocessing — identical to embeddings/generate_clap.py.
SAMPLE_RATE = 48000
DURATION = 10  # seconds
OFFSET = 30    # seconds into the track

_MODEL_CACHE: dict[str, tuple] = {}


def pick_device(prefer: str | None = None) -> torch.device:
    """Resolve a torch device. `prefer` in {"mps","cpu","cuda"} or None (auto)."""
    if prefer:
        return torch.device(prefer)
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def load_model_and_processor(device: torch.device):
    """Load (and cache per-device) the pinned CLAP model + processor in eval mode."""
    key = str(device)
    if key not in _MODEL_CACHE:
        model = ClapModel.from_pretrained(CHECKPOINT, revision=REVISION).to(device)
        model.eval()
        processor = AutoProcessor.from_pretrained(CHECKPOINT, revision=REVISION)
        _MODEL_CACHE[key] = (model, processor)
    return _MODEL_CACHE[key]


def _l2_normalize(x: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(x, axis=-1, keepdims=True)
    norm[norm == 0] = 1.0
    return x / norm


@torch.no_grad()
def encode_texts(texts: list[str], device: torch.device | None = None) -> np.ndarray:
    """
    Encode query strings to L2-normalized 512-d CLAP text embeddings.

    `get_text_features` does not normalize internally (matching the production ONNX text
    encoder in vector/export_clap_text.py, which adds the norm explicitly), so we normalize
    here to make cosine == dot against the normalized stored `v_clap`.
    """
    device = device or pick_device("cpu")  # cheap; CPU keeps the baseline deterministic
    model, processor = load_model_and_processor(device)
    inputs = processor(text=texts, return_tensors="pt", padding=True).to(device)
    feats = model.get_text_features(**inputs).cpu().numpy().astype(np.float32)
    return _l2_normalize(feats)


@torch.no_grad()
def encode_audio(audio_batch: list[np.ndarray], device: torch.device) -> np.ndarray:
    """
    Encode raw mono 48 kHz audio arrays to L2-normalized 512-d CLAP audio embeddings.
    Mirrors embeddings/generate_clap.py get_embeddings_batch.
    """
    model, processor = load_model_and_processor(device)
    inputs = processor(
        audios=audio_batch,
        sampling_rate=SAMPLE_RATE,
        return_tensors="pt",
        padding=True,
    ).to(device)
    feats = model.get_audio_features(**inputs).cpu().numpy().astype(np.float32)
    return _l2_normalize(feats)
