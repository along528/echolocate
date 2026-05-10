"""
Local validation script: verify ONNX text encoder matches PyTorch output.

Run this locally (not deployed) to confirm the export is correct:
    python validate_onnx.py [--onnx-dir ./clap_text_onnx]

Requires both torch/transformers AND onnxruntime/tokenizers installed.
"""

import argparse
import os
import time

import numpy as np
import torch
from transformers import ClapModel, AutoTokenizer
import onnxruntime as ort
from tokenizers import Tokenizer


def validate(onnx_dir: str, model_name: str = "laion/clap-htsat-unfused"):
    test_queries = [
        "warm analog synths with a slow beat",
        "aggressive drums with distorted guitar",
        "calm piano with rain sounds",
        "upbeat electronic dance music with heavy bass",
        "jazz saxophone solo over soft brushes",
    ]

    # --- PyTorch reference ---
    print("Loading PyTorch model...")
    pt_model = ClapModel.from_pretrained(model_name)
    pt_model.eval()
    pt_tokenizer = AutoTokenizer.from_pretrained(model_name)

    print("Running PyTorch inference...")
    t0 = time.time()
    pt_inputs = pt_tokenizer(test_queries, padding=True, return_tensors="pt")
    with torch.no_grad():
        pt_features = pt_model.get_text_features(**pt_inputs)
        pt_features = pt_features / pt_features.norm(dim=-1, keepdim=True)
    pt_out = pt_features.numpy()
    pt_time = time.time() - t0

    # --- ONNX ---
    onnx_path = os.path.join(onnx_dir, "clap_text.onnx")
    tokenizer_path = os.path.join(onnx_dir, "tokenizer.json")

    print(f"Loading ONNX model from {onnx_dir}...")
    session = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
    tokenizer = Tokenizer.from_file(tokenizer_path)
    tokenizer.enable_padding()
    tokenizer.enable_truncation(max_length=512)

    print("Running ONNX inference...")
    t0 = time.time()
    encoded = tokenizer.encode_batch(test_queries)
    input_ids = np.array([e.ids for e in encoded], dtype=np.int64)
    attention_mask = np.array([e.attention_mask for e in encoded], dtype=np.int64)
    [onnx_out] = session.run(None, {"input_ids": input_ids, "attention_mask": attention_mask})
    onnx_time = time.time() - t0

    # --- Compare ---
    print(f"\nPyTorch time:  {pt_time:.3f}s")
    print(f"ONNX time:     {onnx_time:.3f}s")
    print(f"Speedup:       {pt_time / onnx_time:.1f}x")

    max_diff = np.abs(pt_out - onnx_out).max()
    mean_diff = np.abs(pt_out - onnx_out).mean()
    print(f"\nMax abs diff:  {max_diff:.6e}")
    print(f"Mean abs diff: {mean_diff:.6e}")

    # Check cosine similarity between corresponding vectors
    for i, query in enumerate(test_queries):
        cos_sim = np.dot(pt_out[i], onnx_out[i]) / (np.linalg.norm(pt_out[i]) * np.linalg.norm(onnx_out[i]))
        print(f"  [{i}] cosine={cos_sim:.6f}  \"{query}\"")

    tolerance = 1e-4
    if max_diff < tolerance:
        print(f"\nPASSED: max diff {max_diff:.6e} < {tolerance}")
    else:
        print(f"\nFAILED: max diff {max_diff:.6e} >= {tolerance}")
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--onnx-dir", default="./clap_text_onnx")
    parser.add_argument("--model-name", default="laion/clap-htsat-unfused")
    args = parser.parse_args()
    validate(args.onnx_dir, args.model_name)
