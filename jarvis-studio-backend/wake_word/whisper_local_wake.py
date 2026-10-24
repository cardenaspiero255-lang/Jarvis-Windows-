"""Opt-in local Whisper wake recognizer; does not load openWakeWord weights.

Prototype: higher latency/CPU than an acoustic keyword model, not production
certified. Only loads an ALREADY bundled offline faster-whisper model.
"""
from __future__ import annotations

import collections
import math
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from wake_word.capture import heard_wake_phrase

CHUNK_SAMPLES = 1280
WINDOW_SAMPLES = CHUNK_SAMPLES * 36  # 2.88 seconds
HOP_SAMPLES = CHUNK_SAMPLES * 24  # 1.92 seconds
MIN_RMS = 120.0
MIN_DYNAMIC = 80.0


class WakeModelUnavailable(RuntimeError):
    pass


def load_local_whisper(*, bundled_model: Optional[str] = None):
    """Use a local, prefetched model only; never auto-download user speech models."""
    if bundled_model is None:
        # Keep existing packaged-model lookup compatible with JARVIS backend.
        from transcription.whisper_transcriber import _bundled_model_path
        bundled_model = _bundled_model_path()
    if not bundled_model:
        raise WakeModelUnavailable("offline_whisper_wake_model_not_bundled")
    path = Path(bundled_model)
    if path.is_symlink() or not path.is_dir():
        raise WakeModelUnavailable("offline_whisper_wake_model_invalid")
    if not (path / "model.bin").is_file() or not (path / "config.json").is_file():
        raise WakeModelUnavailable("offline_whisper_wake_model_incomplete")
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel(str(path), device="cpu", compute_type="int8")
    except Exception as exc:
        raise WakeModelUnavailable("offline_whisper_wake_load_failed") from exc

    def transcribe(pcm: np.ndarray, prompt: str) -> str:
        # Deliberately NO initial 'Jarvis' prompt: prompt hallucination led to
        # false positive name matches. Do not pass audio to any online service.
        if prompt:
            raise ValueError("wake_transcription_prompt_forbidden")
        x = pcm.astype(np.float32) / 32768.0
        segments, _ = model.transcribe(
            x, language="en", beam_size=1, initial_prompt=None,
            condition_on_previous_text=False, vad_filter=False,
        )
        return " ".join(s.text for s in segments)
    return transcribe


class LocalWhisperWake:
    """Local ASR alternative with exact-word textual acceptance, no OWW weights.

    predict returns 1.0 or 0.0, NOT a calibrated acoustic probability.
    Evaluated only after a ~2.88 s window; reset after activation to prevent
    immediate repeat detection from the same overlapping capture.
    """
    key = "whisper-local-no-pretrained-wake-weights"

    def __init__(self, *, transcribe: Optional[Callable] = None):
        self._transcribe = transcribe if transcribe is not None else load_local_whisper()
        self.reset()

    def reset(self) -> None:
        self._chunks = collections.deque(maxlen=WINDOW_SAMPLES // CHUNK_SAMPLES)
        self._samples_since_check = 0

    def predict(self, audio_data) -> float:
        if (not isinstance(audio_data, np.ndarray)
                or audio_data.dtype != np.int16
                or audio_data.ndim != 1
                or len(audio_data) != CHUNK_SAMPLES):
            raise ValueError("whisper_wake_requires_80ms_pcm16")
        self._chunks.append(audio_data.copy())
        self._samples_since_check += len(audio_data)
        if len(self._chunks) < WINDOW_SAMPLES // CHUNK_SAMPLES:
            return 0.0
        if self._samples_since_check < HOP_SAMPLES and len(self._chunks) == WINDOW_SAMPLES // CHUNK_SAMPLES:
            # First check exactly when the initial buffer becomes full.
            # Afterwards the same window overlaps by 0.96 s.
            if self._samples_since_check != WINDOW_SAMPLES:
                return 0.0
        pcm = np.concatenate(self._chunks)
        rms = float(np.sqrt(np.mean(pcm.astype(np.float64) ** 2)))
        dynamic = float(np.std(pcm.astype(np.float64)))
        if not (math.isfinite(rms) and math.isfinite(dynamic)
                and rms >= MIN_RMS and dynamic >= MIN_DYNAMIC):
            self._samples_since_check = 0
            return 0.0
        self._samples_since_check = 0
        try:
            transcript = self._transcribe(pcm, "")
            match = isinstance(transcript, str) and heard_wake_phrase(transcript)
        except Exception:
            # ASR errors never cause an activation.
            return 0.0
        if match:
            self.reset()
            return 1.0
        return 0.0
