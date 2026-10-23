"""Real-model acceptance on disposable Windows runners (no physical device).

piper: uses exact JARVIS TTSEngine._speak_piper() code and real PiperVoice
synthesis but intercepts playback to audit WAV instead of playing speakers.
wake: uses the actual built-in JARVIS openWakeWord inference wrapper on
16kHz SAPI-recorded English fixtures, and the shipped threshold unmodified.
Never downloads or uploads personal voices, and never reports physical approval.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import sys
import tempfile
import time
import wave

import numpy as np
from neural_voice_contract import piper_verdict, wake_verdict

VOICE = "en_GB-alan-medium"


def _wav_stats(path):
    with wave.open(str(path), "rb") as w:
        rate, channels, width, n = (
            w.getframerate(), w.getnchannels(), w.getsampwidth(),
            w.getnframes())
        if channels != 1 or width != 2 or rate < 16000:
            raise ValueError("unexpected_wav_format")
        samples = np.frombuffer(w.readframes(n), dtype="<i2").astype(np.float64)
    if not len(samples):
        raise ValueError("empty_wav")
    return {
        "sample_rate": rate, "channels": channels, "sample_width": width,
        "duration_s": round(len(samples) / rate, 3),
        "rms": round(float(np.sqrt(np.mean(samples * samples))), 2),
        "peak": int(np.max(np.abs(samples))),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


async def piper_test(scratch):
    from piper import PiperVoice
    from piper.download_voices import download_voice
    from tts.tts_engine import TTSEngine

    folder = scratch / "piper-model"
    folder.mkdir()
    download_voice(VOICE, folder)
    model_file = folder / (VOICE + ".onnx")
    config_file = folder / (VOICE + ".onnx.json")
    if not model_file.is_file() or not config_file.is_file():
        raise RuntimeError("piper_model_assets_missing")
    if model_file.stat().st_size < 100000:
        raise RuntimeError("piper_model_too_small")

    start = time.perf_counter()
    voice = PiperVoice.load(str(model_file))
    load_ms = round((time.perf_counter() - start) * 1000)
    clips = []
    timing = []
    engine = TTSEngine.__new__(TTSEngine)
    engine._stopped = False
    engine._ensure_piper = lambda: voice

    async def inspect_and_unlink(path):
        candidate = Path(path)
        try:
            clips.append(_wav_stats(candidate))
        finally:
            candidate.unlink(missing_ok=True)

    engine._play_file = inspect_and_unlink
    previous_temp = tempfile.tempdir
    tempfile.tempdir = str(scratch)
    try:
        for text in (
            "Good evening. I am Jarvis.",
            "The computer is ready for your command.",
            "Stopping this operation now.",
        ):
            start = time.perf_counter()
            await engine._speak_piper(text)
            timing.append(round((time.perf_counter() - start) * 1000))
        status = piper_verdict(clips)
        if status != "PIPER_SYNTHESIS_PASS":
            raise RuntimeError("piper_waveform_gate_failed")

        # Real ONNX inference must not dispatch playback if a STOP arrives
        # before _speak_piper returns from synthesis. This is not OS mixer
        # interruption certification (that needs separate instrumentation).
        engine._stopped = True
        await engine._speak_piper("This response was cancelled.")
        if len(clips) != 3:
            raise RuntimeError("piper_cancelled_audio_was_dispatched")
        if list(scratch.glob("tmp*.wav")):
            raise RuntimeError("piper_cancelled_wav_leaked")
    finally:
        tempfile.tempdir = previous_temp

    return {
        "status": status,
        "backend_path": "TTSEngine._speak_piper (real PiperVoice)",
        "voice": VOICE,
        "model_sha256": hashlib.sha256(model_file.read_bytes()).hexdigest(),
        "model_load_ms": load_ms,
        "inference_ms": timing,
        "latency_p50_ms_observed": int(statistics.median(timing)),
        "waveforms": clips,
        "cancel_before_playback_prevented": True,
        "latency_statistical_certified": False,
    }


def _load_ci_pcm(path):
    with wave.open(str(path), "rb") as w:
        if (w.getnchannels(), w.getsampwidth(), w.getframerate(),
                w.getcomptype()) != (1, 2, 16000, "NONE"):
            raise ValueError("expected_16khz_pcm_mono")
        data = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").copy()
    if not 16000 <= data.size <= 16_000 * 18:
        raise ValueError("wake_fixture_invalid_duration")
    return data


def _score_clip(model, pcm):
    # 80ms int16/16k exactly as in the Windows JARVIS wake loop.
    chunk = 1280
    pad = np.zeros(6400, dtype=np.int16)  # bounded pre-roll for model startup
    tail = np.zeros(16000, dtype=np.int16)
    sequence = np.concatenate((pad, pcm, tail))
    missing = (-len(sequence)) % chunk
    if missing:
        sequence = np.pad(sequence, (0, missing))
    model.reset()
    scores = []
    start = time.perf_counter()
    for k in range(0, sequence.size, chunk):
        score = float(model.predict(sequence[k:k + chunk]))
        if not math.isfinite(score) or not 0 <= score <= 1:
            raise RuntimeError("nonfinite_wake_score")
        scores.append(score)
    return round(max(scores), 6), int((time.perf_counter() - start) * 1000)


def wake_test(positives, negatives):
    from wake_word.openwakeword import BuiltinInference, _THRESHOLD
    if len(positives) != 2 or len(negatives) != 2:
        raise ValueError("missing_real_audio_fixtures")
    model = BuiltinInference("hey_jarvis")
    ps = [_score_clip(model, _load_ci_pcm(path)) for path in positives]
    ns = [_score_clip(model, _load_ci_pcm(path)) for path in negatives]
    silence = _score_clip(model, np.zeros(48000, dtype=np.int16))
    status = wake_verdict(
        [x[0] for x in ps], [x[0] for x in ns], silence[0], _THRESHOLD)
    return {
        "status": status,
        "backend_path": "wake_word.openwakeword.BuiltinInference",
        "model_key": model.key,
        "threshold": _THRESHOLD,
        "positive_peak_scores": [x[0] for x in ps],
        "negative_peak_scores": [x[0] for x in ns],
        "silence_peak_score": silence[0],
        "inference_ms": [x[1] for x in ps + ns] + [silence[1]],
        "model_inference_executed": True,
        "synthetic_sapi_voice_only": True,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("engine", choices=("piper", "wake"))
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--positive", nargs="*", default=[])
    parser.add_argument("--negative", nargs="*", default=[])
    args = parser.parse_args()
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_OS") != "Windows":
        raise SystemExit("neural voice E2E requires disposable Windows runner")
    root = Path(os.environ["RUNNER_TEMP"]).resolve()
    receipt = Path(args.receipt).resolve()
    if receipt.parent != root:
        raise SystemExit("receipt must remain under disposable RUNNER_TEMP")
    report = {
        "schema": "jarvis-neural-voice-windows-v1",
        "engine": args.engine, "created_utc": datetime.now(timezone.utc).isoformat(),
        "platform": "github-disposable-windows", "status": "NOT_CERTIFIED",
        "physical_microphone_certified": False,
        "physical_speakers_certified": False,
        "signed_release_certified": False,
        "independent_real_voice_corpus_certified": False,
    }
    try:
        if args.engine == "piper":
            with tempfile.TemporaryDirectory(prefix="jarvis-piper-", dir=root) as path:
                detail = asyncio.run(piper_test(Path(path)))
        else:
            paths = [Path(path).resolve() for path in args.positive + args.negative]
            if any(root not in p.parents for p in paths):
                raise RuntimeError("wake_audio_outside_runner")
            detail = wake_test(paths[:2], paths[2:])
        report.update(detail)
    except Exception as exc:
        report["failure_type"] = type(exc).__name__
    receipt.write_text(json.dumps(report, indent=2, sort_keys=True), "utf-8")
    print("JARVIS_NEURAL_VOICE_RESULT=" + json.dumps({
        "engine": args.engine, "status": report["status"],
        "failure_type": report.get("failure_type", "none"),
        "physical_microphone_certified": False
    }, sort_keys=True))
    if report["status"] not in {"PIPER_SYNTHESIS_PASS", "WAKE_ACOUSTIC_PASS"}:
        sys.exit(1)


if __name__ == "__main__":
    main()
