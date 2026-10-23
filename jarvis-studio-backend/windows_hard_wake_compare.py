"""Windows real-model benchmark on frozen Apache-2.0 hard negatives.

Run development first. Holdout job runs only after development passes. No
threshold search, fitting, dataset edits, or positive-recall claims. The second
stage uses JARVIS's real local Whisper and wake-phrase parser, not a stub.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import sys
import urllib.request
from urllib.parse import quote

import numpy as np

from wake_hard_benchmark import (
    FROZEN_SAMPLES, SOURCE_REPO, SOURCE_COMMIT,
    PRODUCTION_THRESHOLD, validate_manifest, score_negative_comparison,
    classification_metrics,
)

def fetch_source(r):
    url = ("https://raw.githubusercontent.com/" + SOURCE_REPO + "/"
           + SOURCE_COMMIT + "/" + quote(r["source_path"], safe="/"))
    request = urllib.request.Request(url, headers={
        "User-Agent": "JARVIS-Window-wake-blind-hard-corpus/1"})
    with urllib.request.urlopen(request, timeout=40) as stream:
        data = stream.read(1_000_001)
    if not 3000 < len(data) < 1_000_000 or not data.startswith((b"RIFF", b"fLaC")):
        raise RuntimeError("invalid_external_audio")
    actual = hashlib.sha1(
        b"blob " + str(len(data)).encode("ascii") + b"\x00" + data
    ).hexdigest()
    if actual != r["git_blob_sha"]:
        raise RuntimeError("source_git_blob_hash_mismatch")
    return data, hashlib.sha256(data).hexdigest()


def load_pcm(data):
    import soundfile as sf
    from scipy.signal import resample_poly
    from math import gcd
    pcm, rate = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
    if not 8000 <= rate <= 192000 or pcm.shape[0] < rate // 2:
        raise ValueError("invalid_audio_rate_or_duration")
    mono = pcm.mean(axis=1)
    if not np.all(np.isfinite(mono)):
        raise ValueError("invalid_nonfinite_audio")
    factor = gcd(int(rate), 16000)
    mono = resample_poly(mono, 16000 // factor, int(rate) // factor)
    if not 0.5 * 16000 <= mono.size <= 15 * 16000:
        raise ValueError("clip_duration_outside_scope")
    if np.sqrt(np.mean(np.square(mono, dtype=np.float64))) <= 0.004:
        raise ValueError("clip_is_silent")
    return (np.clip(mono, -1.0, 1.0) * 32767).astype(np.int16)


def at_snr(pcm, seed_key, snr_db=10):
    if snr_db != 10:
        raise ValueError("snr_not_frozen")
    seed = int.from_bytes(hashlib.sha256(seed_key.encode("ascii")).digest()[:8], "big")
    rng = np.random.default_rng(seed)
    signal = pcm.astype(np.float64)
    power = np.sqrt(np.mean(signal * signal))
    noise = rng.standard_normal(signal.size)
    noise_power = np.sqrt(np.mean(noise * noise))
    if power <= 0 or noise_power <= 0:
        raise ValueError("degenerate_audio")
    noise *= power / (math.sqrt(10) * noise_power)
    return np.clip(np.rint(signal + noise), -32768, 32767).astype(np.int16)


def run(split):
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_OS") != "Windows":
        raise RuntimeError("disposable_windows_ci_only")
    folder = Path(os.environ["RUNNER_TEMP"]).resolve()
    receipt = folder / ("jarvis-hard-voice-" + split + ".json")
    report = {
        "schema": "jarvis-hard-human-wake-comparison-v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "partition": split, "status": "NOT_CERTIFIED",
        "source_repository": SOURCE_REPO, "source_commit": SOURCE_COMMIT,
        "production_threshold": PRODUCTION_THRESHOLD,
        "independent_human_positive_count": 0,
        "speaker_disjointness_verified": False,
        "positive_recall_certified": False,
        "physical_acoustics_certified": False,
        "heldout_model_untouched": True,
        "noise_condition": "seeded_white_noise_at_10dB_snr",
    }
    try:
        problems = validate_manifest(FROZEN_SAMPLES)
        if problems:
            raise RuntimeError("frozen_manifest_invalid")
        from real_neural_voice_e2e import _score_clip
        from wake_word.openwakeword import BuiltinInference, _THRESHOLD
        from wake_word.capture import heard_wake_phrase
        from transcription.whisper_transcriber import _do_transcribe
        if _THRESHOLD != PRODUCTION_THRESHOLD:
            raise RuntimeError("production_threshold_changed")
        model = BuiltinInference("hey_jarvis")
        candidates = [r for r in FROZEN_SAMPLES if r["split"] == split]
        if len(candidates) != 8:
            raise RuntimeError("split_size_not_frozen")
        base_scores, checks, receipts = [], [], []
        for case in candidates:
            data, digest = fetch_source(case)
            original = load_pcm(data)
            for condition, pcm in (
                ("clean", original),
                ("10db_seeded", at_snr(original, case["git_blob_sha"] + "_10db")),
            ):
                peak, elapsed = _score_clip(model, pcm)
                baseline_fire = peak >= _THRESHOLD
                confirmed = False
                if baseline_fire:
                    # Identical Whisper model and initial prompt used by the
                    # capture-based local fallback in JARVIS.
                    transcript = _do_transcribe(pcm, "Jarvis")
                    confirmed = bool(heard_wake_phrase(transcript))
                base_scores.append(peak)
                checks.append(confirmed)
                receipts.append({
                    "source_path": case["source_path"],
                    "git_blob_sha": case["git_blob_sha"],
                    "download_sha256": digest,
                    "recording_phrase": case["phrase"],
                    "variant": condition,
                    "wake_score": peak,
                    "baseline_activation": baseline_fire,
                    "linguistically_verified_activation": confirmed,
                    "inference_ms": elapsed,
                })
        verdict = score_negative_comparison(base_scores, checks, _THRESHOLD)
        if verdict["status"] != "NEGATIVE_COMPARISON_MEASURED":
            raise RuntimeError("invalid_score_comparison")
        metrics = classification_metrics(
            negatives=len(base_scores),
            baseline_fp=verdict["baseline_false_activations"],
            verified_fp=verdict["verified_false_activations"],
            real_positives=0, baseline_tp=0, verified_tp=0,
        )
        report.update(verdict)
        report["metrics"] = metrics
        report["samples"] = receipts
        report["model_name"] = model.key
        report["comparison_effect_seen"] = (
            verdict["baseline_false_activations"] >
            verdict["verified_false_activations"]
        )
        if verdict["verified_false_activations"]:
            report["status"] = "NOT_CERTIFIED"
            report["blocker"] = "human_hard_negative_false_activation"
        else:
            report["status"] = "NEGATIVE_ONLY_MEASURED"
    except Exception as exc:
        report["failure_type"] = type(exc).__name__
        report["status"] = "NOT_CERTIFIED"
    receipt.write_text(json.dumps(report, indent=2, sort_keys=True), "utf-8")
    print("JARVIS_HARD_NEGATIVE_EVAL=" + json.dumps({
        "partition": split, "status": report["status"],
        "samples_evaluated": len(report.get("samples", [])),
        "baseline_fp": report.get("baseline_false_activations"),
        "verified_fp": report.get("verified_false_activations"),
        "failure_type": report.get("failure_type", "none"),
    }, sort_keys=True))
    return 0 if report["status"] == "NEGATIVE_ONLY_MEASURED" else 1


if __name__ == "__main__":
    cli = argparse.ArgumentParser()
    cli.add_argument("--split", choices=("development", "holdout"), required=True)
    args = cli.parse_args()
    sys.exit(run(args.split))
