"""Real Windows SAPI synthesis -> local JARVIS faster-whisper. No mocks.

Runs ONLY on disposable Windows GitHub Actions runners. Generated audio stays
inside RUNNER_TEMP and is deleted by the PowerShell wrapper. Never uploads WAV.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

import numpy as np

from virtual_voice_acceptance import decode_wave, evaluate_transcripts


def _temp_only(value: str) -> Path:
    root = Path(os.environ["RUNNER_TEMP"]).resolve()
    p = Path(value).resolve()
    if p != root and root not in p.parents:
        raise RuntimeError("virtual_audio_path_outside_ephemeral_runner")
    return p


def run(wake_file: Path, negative_file: Path, receipt_file: Path) -> bool:
    receipt = {
        "schema": "jarvis-windows-virtual-voice-v1",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "source": "windows_sapi_synthesized_wave",
        "stt_engine": "actual_jarvis_faster_whisper_base_cpu",
        "platform": "disposable_windows_ci",
        "status": "NOT_CERTIFIED",
        "physical_microphone_certified": False,
        "physical_speakers_certified": False,
        "acoustic_wake_model_certified": False,
        "jarvis_piper_tts_certified": False,
        "permissions_real_os_gui_certified": False,
    }
    try:
        from transcription.whisper_transcriber import _do_transcribe

        wake_pcm, wake_stats = decode_wave(wake_file.read_bytes())
        negative_pcm, negative_stats = decode_wave(negative_file.read_bytes())
        receipt["waveform"] = {"wake": wake_stats, "negative": negative_stats}

        # This is the real CPU Whisper path used by the installed JARVIS
        # fallback, *not* a mocked recognizer or a fixed expected transcript.
        transcript_wake = _do_transcribe(wake_pcm)
        transcript_negative = _do_transcribe(negative_pcm)
        base = evaluate_transcripts(transcript_wake, transcript_negative)
        # Fixed-seed low-level room noise: a reproducible perturbation, not a
        # claim of testing noisy physical microphone or live speaker coupling.
        rng = np.random.default_rng(20261023)
        perturbed = np.clip(
            wake_pcm.astype(np.int32)
            + np.rint(rng.normal(0, 150, size=wake_pcm.size)).astype(np.int32),
            -32768, 32767
        ).astype(np.int16)
        noisy_text = _do_transcribe(perturbed)
        noisy = evaluate_transcripts(noisy_text, transcript_negative)
        receipt["transcription_checks"] = {
            "wake_phrase_found": base["wake_phrase_recognized"],
            "wake_command_has_2_words": len(base["wake_command"].split()) >= 2,
            "negative_phrase_rejected": base["negative_wake_rejected"],
            "noise_150_pcm_rms_wake_survives": noisy["status"] == "VIRTUAL_STT_WAKE_PASS",
            "real_whisper_transcriptions_performed": 3,
        }
        if (base["status"] == "VIRTUAL_STT_WAKE_PASS"
                and noisy["status"] == "VIRTUAL_STT_WAKE_PASS"):
            receipt["status"] = "VIRTUAL_VOICE_ENGINE_PASS"
    except Exception as exc:
        # Do not include exception text: it may contain local profile paths.
        receipt["failure_type"] = type(exc).__name__

    receipt_file.parent.mkdir(parents=True, exist_ok=True)
    receipt_file.write_text(
        json.dumps(receipt, sort_keys=True, indent=2), encoding="utf-8"
    )
    print("JARVIS_VIRTUAL_VOICE_RECEIPT=" + json.dumps({
        "status": receipt["status"],
        "checks": receipt.get("transcription_checks", {}),
        "failure_type": receipt.get("failure_type", "none"),
        "physical_microphone_certified": False,
        "acoustic_wake_model_certified": False,
    }, sort_keys=True))
    return receipt["status"] == "VIRTUAL_VOICE_ENGINE_PASS"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--wake", required=True)
    p.add_argument("--negative", required=True)
    p.add_argument("--receipt", required=True)
    args = p.parse_args()
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_OS") != "Windows":
        print("Virtual audio test requires disposable Windows CI", file=sys.stderr)
        return 2
    try:
        wake, negative, receipt = (
            _temp_only(args.wake), _temp_only(args.negative), _temp_only(args.receipt)
        )
        return 0 if run(wake, negative, receipt) else 1
    except Exception as exc:
        print("Virtual audio setup failed: " + type(exc).__name__, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
