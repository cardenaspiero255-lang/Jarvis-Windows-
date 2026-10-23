"""Offline virtual audio acceptance for Windows CI.

Real Windows SAPI PCM WAV -> JARVIS faster-whisper -> wake phrase parser.
This tests *model inference* with actual generated speech, but never asserts
physical microphone, speaker, JARVIS Piper, or acoustic wake-model validation.
"""
from __future__ import annotations

import io
import math
import wave

import numpy as np

from wake_word.capture import command_after_wake, heard_wake_phrase, is_noise

SAMPLE_RATE = 16_000
MIN_SECONDS = 1.0
MAX_SECONDS = 25.0


def decode_wave(data: bytes) -> tuple[np.ndarray, dict]:
    """Accept only non-silent 16-kHz mono PCM16 WAV; refuse conversion guesses."""
    if not isinstance(data, bytes) or len(data) < 44:
        raise ValueError("wav_missing_or_truncated")
    try:
        with wave.open(io.BytesIO(data), "rb") as wav:
            if wav.getcomptype() != "NONE" or wav.getnchannels() != 1:
                raise ValueError("wav_unexpected_encoding_or_channels")
            if wav.getsampwidth() != 2 or wav.getframerate() != SAMPLE_RATE:
                raise ValueError("wav_unexpected_sample_format")
            frames = wav.readframes(wav.getnframes())
    except (EOFError, wave.Error, OSError) as exc:
        raise ValueError("wav_invalid") from exc
    pcm = np.frombuffer(frames, dtype="<i2").copy()
    seconds = len(pcm) / SAMPLE_RATE
    if not MIN_SECONDS <= seconds <= MAX_SECONDS:
        raise ValueError("wav_invalid_duration")
    x = pcm.astype(np.float64)
    rms = float(np.sqrt(np.mean(x * x)))
    dynamic = float(np.std(x))
    if not math.isfinite(rms) or rms < 250 or dynamic < 100:
        raise ValueError("wav_silent_or_constant")
    return pcm, {
        "sample_rate": SAMPLE_RATE,
        "duration_seconds": round(seconds, 3),
        "rms": round(rms, 1),
        "peak": int(np.max(np.abs(x))),
    }


def evaluate_transcripts(wake_text: str, negative_text: str) -> dict:
    """Compare actual transcripts, never trust labels of the source WAV files."""
    wake_command = command_after_wake(wake_text)
    accepted = bool(
        isinstance(wake_text, str)
        and isinstance(negative_text, str)
        and heard_wake_phrase(wake_text)
        and wake_command
        and len(wake_command.split()) >= 2
        and not is_noise(wake_text)
        and not is_noise(negative_text)
        and len(negative_text.split()) >= 4
        and not heard_wake_phrase(negative_text)
    )
    return {
        "status": "VIRTUAL_STT_WAKE_PASS" if accepted else "NOT_CERTIFIED",
        "wake_phrase_recognized": bool(heard_wake_phrase(wake_text)),
        "wake_command": wake_command if wake_command is not None else "",
        "negative_wake_rejected": bool(negative_text and not heard_wake_phrase(negative_text)),
        "physical_microphone_certified": False,
        "jarvis_tts_certified": False,
        "physical_speakers_certified": False,
        "acoustic_wake_model_certified": False,
    }
