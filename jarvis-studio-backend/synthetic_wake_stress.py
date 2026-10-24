"""Reproducible *synthetic* Windows SAPI stress campaign for JARVIS wake word.

Source voices are the installed SAPI voices, NOT independent human speakers.
We evaluate the actual built-in ONNX model at the production threshold, never
train or change the threshold, and never count augmentations as new voices.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import time
import wave

import numpy as np

from wake_hard_benchmark import PRODUCTION_THRESHOLD
from wake_word.capture import heard_wake_phrase

VARIANTS = ("clean", "noise_20db", "noise_10db", "distant_simulated")
KINDS = frozenset(("synthetic_positive", "synthetic_negative"))
EXPECTED_BASE = {"smoke": 6, "campaign": 60}
SHA_PATTERN = re.compile(r"[a-f0-9]{64}\Z")
NAME_PATTERN = re.compile(r"sapi-[0-9]{3}\.wav\Z")
WAKE = re.compile(r"\bhey\s+jarvis\b", re.IGNORECASE)


def frozen_threshold() -> float:
    return PRODUCTION_THRESHOLD


def _read_wav(file: Path) -> np.ndarray:
    try:
        with wave.open(str(file), "rb") as wav:
            if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(),
                    wav.getcomptype()) != (1, 2, 16000, "NONE"):
                raise ValueError("invalid_wav")
            n = wav.getnframes()
            if not 8000 <= n <= 240000:
                raise ValueError("invalid_wav")
            data = wav.readframes(n)
    except (OSError, EOFError, wave.Error) as exc:
        raise ValueError("invalid_wav") from exc
    samples = np.frombuffer(data, dtype="<i2").copy()
    if len(samples) != n:
        raise ValueError("invalid_wav")
    rms = np.sqrt(np.mean(samples.astype(np.float64) ** 2))
    if not math.isfinite(float(rms)) or rms < 60:
        raise ValueError("invalid_wav")
    return samples


def validate_manifest(manifest: dict, root: Path) -> list[str]:
    if not isinstance(manifest, dict) or manifest.get("schema") != 1:
        return ["invalid_schema"]
    profile = manifest.get("profile")
    if profile not in EXPECTED_BASE:
        return ["invalid_profile"]
    samples = manifest.get("samples")
    if not isinstance(samples, list) or len(samples) != EXPECTED_BASE[profile]:
        return ["wrong_profile_count"]
    root = Path(root)
    seen = set()
    errors = []
    labels = []
    for item in samples:
        if not isinstance(item, dict):
            errors.append("invalid_sample")
            continue
        name = item.get("file")
        if not isinstance(name, str) or not NAME_PATTERN.fullmatch(name):
            errors.append("invalid_audio_filename")
            continue
        if name in seen:
            errors.append("duplicate_file")
            continue
        seen.add(name)
        if item.get("source_kind") != "windows_sapi_synthetic":
            errors.append("invalid_source_kind")
        label = item.get("label")
        if label not in KINDS:
            errors.append("invalid_label")
        else:
            labels.append(label)
        text = item.get("text")
        if not isinstance(text, str) or not 4 <= len(text) <= 240:
            errors.append("invalid_text")
        elif label == "synthetic_positive" and not WAKE.search(text):
            errors.append("positive_missing_wake")
        elif label == "synthetic_negative" and WAKE.search(text):
            errors.append("negative_contains_wake")
        if (not isinstance(item.get("voice_id"), str)
                or not 1 <= len(item["voice_id"]) <= 200):
            errors.append("invalid_voice_id")
        if (not isinstance(item.get("locale"), str)
                or not 2 <= len(item["locale"]) <= 20):
            errors.append("invalid_locale")
        if type(item.get("rate")) is not int or item["rate"] not in (-2, -1, 0, 1, 2):
            errors.append("invalid_sapi_rate")
        sha = item.get("sha256")
        if not isinstance(sha, str) or not SHA_PATTERN.fullmatch(sha):
            errors.append("invalid_sha256")
            continue
        file = root / name
        if file.is_symlink() or not file.is_file() or not 1000 <= file.stat().st_size <= 500000:
            errors.append("invalid_wav")
            continue
        if hashlib.sha256(file.read_bytes()).hexdigest() != sha:
            errors.append("file_hash_mismatch")
            continue
        try:
            _read_wav(file)
        except ValueError:
            errors.append("invalid_wav")
    count = EXPECTED_BASE[profile] // 2
    if labels.count("synthetic_positive") != count or labels.count("synthetic_negative") != count:
        errors.append("unbalanced_labels")
    return sorted(set(errors))


def perturb_pcm(pcm: np.ndarray, variant: str, seed_key: str) -> np.ndarray:
    if variant not in VARIANTS:
        raise ValueError("unknown_augmentation")
    if pcm.dtype != np.int16 or pcm.ndim != 1 or pcm.size == 0:
        raise ValueError("invalid_pcm")
    if variant == "clean":
        return pcm.copy()
    signal = pcm.astype(np.float64)
    if variant == "distant_simulated":
        # Synthetic attenuation + short echo, NOT measured real-room distance.
        echo = np.zeros_like(signal)
        echo[960:] = signal[:-960] * 0.18
        signal = signal * 0.48 + echo
    else:
        snr = 20 if variant == "noise_20db" else 10
        seed = int.from_bytes(hashlib.sha256(
            (seed_key + ":" + variant).encode("utf-8")).digest()[:8], "big")
        rng = np.random.default_rng(seed)
        noise = rng.standard_normal(len(signal))
        rms_signal = float(np.sqrt(np.mean(signal * signal)))
        rms_noise = float(np.sqrt(np.mean(noise * noise)))
        if rms_signal < 1 or rms_noise < 1e-12:
            raise ValueError("invalid_audio_for_noise")
        signal += noise * (rms_signal / (10 ** (snr / 20) * rms_noise))
    return np.clip(np.rint(signal), -32768, 32767).astype(np.int16)


def synthetic_metrics(records: list[dict], *, verifier_used: bool) -> dict:
    if not isinstance(records, list) or not records:
        raise ValueError("missing_inference")
    plus, minus = [], []
    for item in records:
        if not isinstance(item, dict) or item.get("label") not in KINDS:
            raise ValueError("invalid_observation")
        value = item.get("score")
        if type(value) not in (float, int) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError("invalid_model_score")
        confirmed = item.get("verified")
        if verifier_used:
            if type(confirmed) is not bool:
                raise ValueError("missing_verifier_decision")
            if confirmed and value < PRODUCTION_THRESHOLD:
                raise ValueError("verifier_without_acoustic_trigger")
        elif confirmed is not None:
            raise ValueError("verifier_claim_without_running_it")
        (plus if item["label"] == "synthetic_positive" else minus).append(item)
    if not plus or not minus:
        raise ValueError("missing_class")
    triggered = lambda rows: sum(s["score"] >= PRODUCTION_THRESHOLD for s in rows)
    verified = lambda rows: sum(s["verified"] is True for s in rows)
    return {
        "threshold": PRODUCTION_THRESHOLD,
        "synthetic_positive_cases": len(plus),
        "synthetic_negative_cases": len(minus),
        "synthetic_positive_baseline_recall": triggered(plus) / len(plus),
        "synthetic_negative_baseline_false_activations": triggered(minus),
        "synthetic_negative_baseline_fpr_per_case": triggered(minus) / len(minus),
        "synthetic_positive_verified_recall": (
            verified(plus) / len(plus) if verifier_used else None),
        "synthetic_negative_verified_false_activations": (
            verified(minus) if verifier_used else None),
        "synthetic_negative_verified_fpr_per_case": (
            verified(minus) / len(minus) if verifier_used else None),
        "human_positive_false_reject_rate": None,
        "real_world_false_alarms_per_hour": None,
    }


def summarize_experiment(rows: list[dict], *, verifier_used: bool) -> dict:
    return {
        "schema": "jarvis-synthetic-wake-stress-v1",
        "status": "SYNTHETIC_ONLY_MEASURED",
        "metrics": synthetic_metrics(rows, verifier_used=verifier_used),
        "synthetic_source_voice_count": len({r["voice_id"] for r in rows}),
        "evaluated_conditions": sorted({r["variant"] for r in rows}),
        "evaluated_augmented_cases": len(rows),
        "independent_human_positive_count": 0,
        "human_positive_certified": False,
        "independent_speaker_certified": False,
        "physical_microphone_certified": False,
        "commercial_model_rights_certified": False,
        "holds_no_audio_files": True,
    }


def compare_prompt_strategies(rows: list[dict]) -> dict:
    """Compare fixed production 'Jarvis' prompt against an unprompted experiment.

    Development diagnostics only; neither branch is a new blind human holdout.
    The unprompted strategy must not be deployed or selected on the same data.
    """
    production = synthetic_metrics(rows, verifier_used=True)
    alternate = []
    for row in rows:
        verdict = row.get("verified_unprompted")
        if type(verdict) is not bool:
            raise ValueError("unprompted_verifier_missing")
        alternate.append({**row, "verified": verdict})
    alternative = synthetic_metrics(alternate, verifier_used=True)
    return {
        "mode": "DIAGNOSTIC_NOT_DEPLOYED",
        "production_verified_positive_recall": production["synthetic_positive_verified_recall"],
        "production_verified_negative_false_activations":
            production["synthetic_negative_verified_false_activations"],
        "experimental_unprompted_positive_recall":
            alternative["synthetic_positive_verified_recall"],
        "experimental_unprompted_negative_false_activations":
            alternative["synthetic_negative_verified_false_activations"],
        "positive_cases": production["synthetic_positive_cases"],
        "negative_cases": production["synthetic_negative_cases"],
        "human_positive_certified": False,
        "release_certified": False,
        "production_wake_verifier_unchanged": True,
    }


def run(manifest_path: Path, *, receipt: Path, with_whisper: bool,
        compare_unprompted: bool = False) -> int:
    # This experimental runner is for disposable Windows CI or explicitly
    # authorized local experimentation; it never records the microphone.
    report = {
        "schema": "jarvis-synthetic-wake-stress-v1", "status": "NOT_CERTIFIED",
        "independent_human_positive_count": 0, "human_positive_certified": False,
    }
    try:
        if compare_unprompted and not with_whisper:
            raise ValueError('unprompted comparison requires real Whisper')
        manifest_path = manifest_path.resolve(strict=True)
        folder = manifest_path.parent
        manifest = json.loads(manifest_path.read_text("utf-8"))
        errs = validate_manifest(manifest, folder)
        if errs:
            raise ValueError(",".join(errs))
        from wake_word.openwakeword import BuiltinInference, _THRESHOLD
        from real_neural_voice_e2e import _score_clip
        if _THRESHOLD != PRODUCTION_THRESHOLD:
            raise RuntimeError("production_threshold_changed")
        model = BuiltinInference("hey_jarvis")
        if with_whisper:
            from transcription.whisper_transcriber import _do_transcribe
        rows = []
        started = time.perf_counter()
        for item in manifest["samples"]:
            pcm = _read_wav(folder / item["file"])
            for variant in VARIANTS:
                audio = perturb_pcm(pcm, variant, item["sha256"])
                score, elapsed = _score_clip(model, audio)
                fired = score >= PRODUCTION_THRESHOLD
                verified = None
                if with_whisper:
                    verified = bool(heard_wake_phrase(
                        _do_transcribe(audio, "Jarvis"))) if fired else False
                unprompted = None
                if compare_unprompted:
                    unprompted = bool(heard_wake_phrase(
                        _do_transcribe(audio, ""))) if fired else False
                rows.append({
                    "file": item["file"], "voice_id": item["voice_id"],
                    "label": item["label"], "variant": variant,
                    "score": score, "verified": verified,
                    "verified_unprompted": unprompted,
                    "inference_ms": elapsed,
                })
        report.update(summarize_experiment(rows, verifier_used=with_whisper))
        if compare_unprompted:
            report['experimental_unprompted_comparison'] = compare_prompt_strategies(rows)
        report.update({
            "profile": manifest["profile"],
            "generated_source_wav_count": len(manifest["samples"]),
            "wall_time_ms": int((time.perf_counter() - started) * 1000),
            "source_engine": "Windows_SAPI_synthetic",
            "acoustic_backend": "real_openWakeWord_builtin_hey_jarvis",
            "whisper_verifier_executed": with_whisper,
            "model_license_cleared_for_commercial_release": False,
            "generated_utc": datetime.now(timezone.utc).isoformat(),
        })
        # No raw WAVs or transcripts in receipts. Voice labels reflect installed
        # SAPI identities, not 240 independent speakers.
        report["cases"] = rows
    except Exception as exc:
        report["status"] = "NOT_CERTIFIED"
        report["failure_type"] = type(exc).__name__
        # Do not print raw audio paths, private names, or transcripts.
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps(report, indent=2, sort_keys=True), "utf-8")
    print("JARVIS_SYNTHETIC_WAKE=" + json.dumps({
        "status": report["status"],
        "profile": report.get("profile", "unavailable"),
        "cases": report.get("evaluated_augmented_cases", 0),
        "source_voices": report.get("synthetic_source_voice_count", 0),
        "failure_type": report.get("failure_type", "none"),
        "synthetic_metrics": report.get("metrics"),
        "experimental_unprompted_comparison": report.get("experimental_unprompted_comparison"),
        "human_positive_certified": False,
    }, sort_keys=True))
    return 0 if report["status"] == "SYNTHETIC_ONLY_MEASURED" else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--with-whisper", action="store_true")
    parser.add_argument("--compare-unprompted", action="store_true")
    args = parser.parse_args()
    if (os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("RUNNER_OS") != "Windows"):
        raise SystemExit("synthetic benchmark CLI requires disposable Windows CI")
    scratch = Path(os.environ["RUNNER_TEMP"]).resolve()
    manifest = args.manifest.resolve()
    receipt = args.receipt.resolve()
    if manifest.parent != scratch or receipt.parent != scratch:
        raise SystemExit("manifest and receipt must be under RUNNER_TEMP")
    return run(manifest, receipt=receipt, with_whisper=args.with_whisper,
               compare_unprompted=args.compare_unprompted)


if __name__ == "__main__":
    sys.exit(main())
