"""Fail-closed 6-speaker REAL human-accent corpus inference on Windows.

The six sources are frozen in wake_independent_corpus.py BEFORE analysis.
No score-based sample selection or threshold changes. External URLs are pinned
to a Git commit and each downloaded FLAC is verified by its Git blob SHA-1.
No audio bytes are persisted or included in GitHub artifacts.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import urllib.request
from urllib.parse import quote

import numpy as np

from wake_independent_corpus import (
    FROZEN_NEGATIVE_MANIFEST, FROZEN_PRODUCTION_THRESHOLD,
    REQUIRED_SOURCE_COMMIT, SOURCE_REPOSITORY,
    validate_manifest, adjudicate_negative_scores,
)


def fetch_verified_flac(item: dict) -> tuple[bytes, str]:
    path = item["source_path"]
    url = (
        "https://raw.githubusercontent.com/" + SOURCE_REPOSITORY + "/"
        + REQUIRED_SOURCE_COMMIT + "/" + quote(path, safe="/")
    )
    request = urllib.request.Request(
        url, headers={"User-Agent": "JARVIS-Windows-independent-corpus-audit/1.0"})
    with urllib.request.urlopen(request, timeout=35) as response:
        data = response.read(2_000_001)
    if not 1000 <= len(data) <= 2_000_000:
        raise RuntimeError("invalid_external_clip_size")
    if not data.startswith(b"fLaC"):
        raise RuntimeError("external_clip_not_flac")
    blob = hashlib.sha1(b"blob " + str(len(data)).encode("ascii")
                        + b"\x00" + data).hexdigest()
    if blob != item["git_blob_sha"]:
        raise RuntimeError("external_clip_git_sha_mismatch")
    return data, hashlib.sha256(data).hexdigest()


def decode_real_recording(data: bytes) -> np.ndarray:
    # scipy resample_poly retains an anti-aliasing filter; ordinary interpolation
    # could introduce spurious high-frequency wake cues.
    import soundfile as sf
    from scipy.signal import resample_poly
    from math import gcd

    audio, rate = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
    if rate < 8000 or rate > 192000 or audio.shape[0] < rate:
        raise ValueError("recording_sample_rate_duration_unusable")
    mono = np.mean(audio, axis=1)
    if not np.all(np.isfinite(mono)):
        raise ValueError("nonfinite_audio")
    divisor = gcd(int(rate), 16000)
    signal = resample_poly(mono, 16000 // divisor, int(rate) // divisor)
    if not 16000 <= signal.size <= 20 * 16000:
        raise ValueError("human_negative_duration_out_of_range")
    if float(np.sqrt(np.mean(np.square(signal, dtype=np.float64)))) < 0.008:
        raise ValueError("human_negative_silent")
    return (np.clip(signal, -1.0, 1.0) * 32767).astype(np.int16)


def run() -> int:
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_OS") != "Windows":
        print("Independent voice corpus requires disposable Windows CI", file=sys.stderr)
        return 2
    root = Path(os.environ["RUNNER_TEMP"]).resolve()
    receipt = root / "jarvis-independent-human-wake-receipt.json"
    report = {
        "schema": "jarvis-independent-wake-negative-corpus-v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source_repository": SOURCE_REPOSITORY,
        "source_commit": REQUIRED_SOURCE_COMMIT,
        "license_as_documented_by_source": "CC0-1.0",
        "real_human_negative_speech_only": True,
        "source_accent_labels_independently_verified": False,
        "holdout_manifest_frozen_before_inference": True,
        "production_threshold_unchanged": FROZEN_PRODUCTION_THRESHOLD,
        "status": "NOT_CERTIFIED",
        "physical_microphone_certified": False,
        "independent_positive_corpus_certified": False,
        "entire_wake_acoustic_gate_certified": False,
    }
    try:
        problems = validate_manifest(FROZEN_NEGATIVE_MANIFEST)
        if problems:
            raise ValueError("invalid_frozen_manifest")
        from wake_word.openwakeword import BuiltinInference, _THRESHOLD
        from real_neural_voice_e2e import _score_clip
        if _THRESHOLD != FROZEN_PRODUCTION_THRESHOLD:
            raise RuntimeError("production_threshold_changed")
        model = BuiltinInference("hey_jarvis")
        scores, receipts = {}, []
        for item in FROZEN_NEGATIVE_MANIFEST:
            data, digest = fetch_verified_flac(item)
            pcm = decode_real_recording(data)
            peak, latency_ms = _score_clip(model, pcm)
            scores[item["speaker"]] = peak
            receipts.append({
                "speaker": item["speaker"],  # public corpus reader ID only
                "accent_as_documented_by_source": item["accent"],
                "source_path": item["source_path"],
                "git_blob_sha": item["git_blob_sha"],
                "download_sha256": digest,
                "duration_s": round(pcm.size / 16000, 3),
                "peak_wake_score": peak,
                "inference_ms": latency_ms,
            })
        verdict = adjudicate_negative_scores(FROZEN_NEGATIVE_MANIFEST, scores, _THRESHOLD)
        report.update(verdict)
        report["samples"] = receipts
        report["model_id"] = model.key
    except Exception as exc:
        # Do not publish exception messages which may include runner/user paths.
        report["failure_type"] = type(exc).__name__
        report["status"] = "NOT_CERTIFIED"
    receipt.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print("INDEPENDENT_HUMAN_WAKE_NEGATIVES=" + json.dumps({
        "status": report["status"],
        "tested_speakers": len(report.get("samples", [])),
        "false_activations": report.get("false_activation_count", "unknown"),
        "error_type": report.get("failure_type", "none"),
        "production_threshold_unchanged": True,
    }, sort_keys=True))
    return 0 if report["status"] == "NEGATIVE_HUMAN_CORPUS_PASS" else 1


if __name__ == "__main__":
    sys.exit(run())
