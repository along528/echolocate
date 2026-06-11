"""
Tier 2: audio captioning with Gemini 2.0 Flash on Vertex AI.

Sends an audio snippet per track (default: 30s starting at 0:30, 16kHz mono
WAV inline) and asks for structured JSON: a one-sentence caption in the same
technical register vector-rs uses for CLAP query expansion, plus 3-5 short
vibe tags. Captions in that register embed well with the CLAP text encoder,
which evaluate_captions.py relies on for cycle-consistency verification.

By default the prompt contains NO track metadata (title/artist/album) so the
caption describes the audio, not Gemini's textual priors about the artist.

Auth: Application Default Credentials (gcloud auth application-default login).
Project comes from --project or GOOGLE_CLOUD_PROJECT / GCP_PROJECT_ID.

Usage:
    python generate_captions.py [--limit N] [--source library|fma|all]
                                [--db PATH] [--output PATH] [--audio-root DIR]
                                [--offset SEC] [--duration SEC]
                                [--include-metadata] [--sleep SEC]

Resumable: ids already present in the output JSONL are skipped on re-run.
"""

import argparse
import base64
import io
import json
import os
import sys
import time
import wave

import numpy as np
from tqdm import tqdm

from corpus import ARTIFACTS_DIR, DEFAULT_DB, connect

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
DEFAULT_OUTPUT = os.path.join(ARTIFACTS_DIR, "captions.jsonl")

GEMINI_MODEL = "gemini-2.0-flash-001"
GEMINI_LOCATION = "us-central1"
SNIPPET_SR = 16000  # mono 16kHz keeps a 30s inline payload ~1MB

SYSTEM_INSTRUCTION = (
    "You are an expert musicologist and audio engineer. Describe the music "
    "clip you hear. Return JSON with two fields: "
    "'caption': ONE technical sentence under 30 words covering genre, "
    "instrumentation, mood, texture, and tempo (the style of a LAION-CLAP "
    "audio caption); "
    "'vibes': 3-5 short lowercase descriptive tags. "
    "Describe only what you hear. Do not guess the artist or song title."
)

RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "caption": {"type": "STRING"},
        "vibes": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["caption", "vibes"],
}


class GeminiCaptioner:
    def __init__(self, project_id, location=GEMINI_LOCATION, model=GEMINI_MODEL):
        import google.auth
        import google.auth.transport.requests
        import requests

        self._requests = requests
        self._auth_request = google.auth.transport.requests.Request()
        self.credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        self.endpoint = (
            f"https://{location}-aiplatform.googleapis.com/v1/projects/"
            f"{project_id}/locations/{location}/publishers/google/models/"
            f"{model}:generateContent"
        )
        self.model = model

    def _token(self):
        if not self.credentials.valid:
            self.credentials.refresh(self._auth_request)
        return self.credentials.token

    def caption(self, wav_bytes: bytes, metadata_hint: str = None,
                max_retries: int = 5):
        parts = [{
            "inlineData": {
                "mimeType": "audio/wav",
                "data": base64.b64encode(wav_bytes).decode("ascii"),
            }
        }]
        if metadata_hint:
            parts.append({"text": f"Track metadata (for context only): {metadata_hint}"})

        body = {
            "contents": [{"role": "user", "parts": parts}],
            "systemInstruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
            "generationConfig": {
                "temperature": 0.3,
                "maxOutputTokens": 200,
                "candidateCount": 1,
                "responseMimeType": "application/json",
                "responseSchema": RESPONSE_SCHEMA,
            },
        }

        delay = 2.0
        for attempt in range(max_retries):
            resp = self._requests.post(
                self.endpoint,
                headers={"Authorization": f"Bearer {self._token()}"},
                json=body,
                timeout=120,
            )
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == max_retries - 1:
                    raise RuntimeError(f"Gemini API error {resp.status_code}: {resp.text[:200]}")
                time.sleep(delay)
                delay *= 2
                continue
            if not resp.ok:
                raise RuntimeError(f"Gemini API error {resp.status_code}: {resp.text[:200]}")
            data = resp.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text)
        raise RuntimeError("unreachable")


def load_snippet(path: str, offset: float, duration: float) -> bytes:
    """Load audio and return 16kHz mono 16-bit WAV bytes, or None on failure."""
    import librosa

    audio, _ = librosa.load(path, sr=SNIPPET_SR, mono=True,
                            offset=offset, duration=duration)
    if len(audio) < SNIPPET_SR:  # need at least 1s
        # Short track: retry from the start.
        audio, _ = librosa.load(path, sr=SNIPPET_SR, mono=True, duration=duration)
        if len(audio) < SNIPPET_SR:
            return None
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SNIPPET_SR)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def select_tracks(con, source: str, limit: int):
    tables = {"library": ["tracks_library"], "fma": ["tracks_fma"]}.get(
        source, ["tracks_library", "tracks_fma"]
    )
    rows = []
    for table in tables:
        rows += [
            (table,) + r
            for r in con.execute(
                f"SELECT id, relative_path, title, artist, album FROM {table}"
            ).fetchall()
        ]
    if limit:
        rows = rows[:limit]
    return rows


def generate_captions(args):
    project_id = (
        args.project
        or os.environ.get("GOOGLE_CLOUD_PROJECT")
        or os.environ.get("GCP_PROJECT_ID")
    )
    if not project_id:
        sys.exit("No GCP project: pass --project or set GOOGLE_CLOUD_PROJECT.")

    # Resume: skip ids already captioned.
    done = set()
    if os.path.exists(args.output):
        with open(args.output) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        done.add(json.loads(line)["id"])
                    except (json.JSONDecodeError, KeyError):
                        pass
        print(f"Resume: {len(done)} tracks already captioned.")

    con = connect(args.db)
    rows = select_tracks(con, args.source, args.limit)
    con.close()
    todo = [r for r in rows if r[1] not in done]
    print(f"{len(rows)} tracks selected, {len(todo)} to caption.")
    if not todo:
        return

    captioner = GeminiCaptioner(project_id, args.location)
    os.makedirs(os.path.dirname(args.output), exist_ok=True)

    ok, missing, errors = 0, 0, 0
    with open(args.output, "a") as out_f:
        for table, tid, rel_path, title, artist, album in tqdm(
            todo, desc="Captioning", unit="trk"
        ):
            audio_path = os.path.join(args.audio_root, rel_path)
            if not os.path.exists(audio_path):
                missing += 1
                continue
            try:
                wav = load_snippet(audio_path, args.offset, args.duration)
                if wav is None:
                    missing += 1
                    continue
                hint = (
                    f"{artist} — {title} ({album})" if args.include_metadata else None
                )
                result = captioner.caption(wav, metadata_hint=hint)
                out_f.write(json.dumps({
                    "id": tid,
                    "table": table,
                    "caption": result.get("caption", "").strip(),
                    "vibes": result.get("vibes", []),
                    "model": GEMINI_MODEL,
                    "audio": {"offset": args.offset, "duration": args.duration,
                              "sr": SNIPPET_SR},
                }) + "\n")
                out_f.flush()
                ok += 1
            except Exception as e:
                errors += 1
                print(f"\n  ⚠️  {rel_path}: {e}")
            if args.sleep:
                time.sleep(args.sleep)

    print(f"\n✅ Captioned {ok} tracks ({missing} missing audio, {errors} errors)")
    print(f"   Output: {args.output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gemini audio captioning")
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--audio-root", default=PROJECT_ROOT,
                        help="Directory that relative_path values resolve against")
    parser.add_argument("--source", choices=["library", "fma", "all"], default="all")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--offset", type=float, default=30.0)
    parser.add_argument("--duration", type=float, default=30.0)
    parser.add_argument("--project", default=None, help="GCP project id")
    parser.add_argument("--location", default=GEMINI_LOCATION)
    parser.add_argument("--include-metadata", action="store_true",
                        help="Include artist/title in the prompt (default: audio only)")
    parser.add_argument("--sleep", type=float, default=0.0,
                        help="Seconds to sleep between requests (rate limiting)")
    generate_captions(parser.parse_args())
