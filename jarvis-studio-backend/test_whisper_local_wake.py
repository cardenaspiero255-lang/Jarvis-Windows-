"""Tests for the optional clean-license offline Whisper wake phrase prototype."""
import unittest

import numpy as np

from wake_word.whisper_local_wake import (
    LocalWhisperWake, WakeModelUnavailable, load_local_whisper,
    WINDOW_SAMPLES, HOP_SAMPLES,
)


class LocalWhisperWakeTests(unittest.TestCase):
    def _drive(self, detector, length):
        scores = []
        for _ in range(length // 1280):
            scores.append(detector.predict(np.full(1280, 2500, dtype=np.int16)))
        return scores

    def test_exact_hey_jarvis_activates_without_prompted_stt(self):
        prompts = []
        def transcribe(audio, prompt):
            prompts.append(prompt)
            self.assertEqual(audio.dtype, np.int16)
            return "Hey Jarvis, open notes."
        detector = LocalWhisperWake(transcribe=transcribe)
        scores = self._drive(detector, WINDOW_SAMPLES)
        self.assertEqual(max(scores), 1.0)
        self.assertEqual(prompts, [""])
        self.assertEqual(detector.key, "whisper-local-no-pretrained-wake-weights")
        self.assertEqual(scores[-1], 1.0)

    def test_hey_travis_and_mentions_do_not_activate(self):
        for utterance in ("Hey Travis, open notes.", "Jarvis is a digital assistant.",
                          "Hey Jarvison, open notes.", "Hello Chervis, open notes."):
            with self.subTest(utterance=utterance):
                detector = LocalWhisperWake(transcribe=lambda pcm, prompt: utterance)
                self.assertEqual(max(self._drive(detector, WINDOW_SAMPLES)), 0.0)

    def test_no_silence_hallucination_and_no_duplicate_activation(self):
        calls = []
        detector = LocalWhisperWake(transcribe=lambda pcm, prompt: calls.append(1) or "Hey Jarvis")
        zero = np.zeros(1280, dtype=np.int16)
        self.assertEqual([detector.predict(zero) for _ in range(40)], [0] * 40)
        self.assertEqual(calls, [])
        scores = self._drive(detector, WINDOW_SAMPLES * 2)
        self.assertEqual(scores.count(1.0), 1)

    def test_only_whisper_window_is_transcribed_at_hop_rate(self):
        calls = []
        detector = LocalWhisperWake(transcribe=lambda pcm, prompt: calls.append(len(pcm)) or "no")
        scores = self._drive(detector, WINDOW_SAMPLES + HOP_SAMPLES)
        self.assertEqual(max(scores), 0.0)
        self.assertEqual(calls, [WINDOW_SAMPLES, WINDOW_SAMPLES])

    def test_reset_flushes_previously_captured_speech(self):
        detector = LocalWhisperWake(transcribe=lambda pcm, prompt: "Hey Jarvis")
        self._drive(detector, WINDOW_SAMPLES - 1280)
        detector.reset()
        self.assertEqual(detector.predict(np.full(1280, 2000, dtype=np.int16)), 0.0)

    def test_bad_pcm_and_transcriber_failure_deny_trigger(self):
        detector = LocalWhisperWake(transcribe=lambda pcm, prompt: "Hey Jarvis")
        with self.assertRaises(ValueError):
            detector.predict(np.full(1280, np.nan, dtype=np.float32))
        detector = LocalWhisperWake(transcribe=lambda pcm, prompt: (_ for _ in ()).throw(RuntimeError("model unavailable")))
        self.assertEqual(max(self._drive(detector, WINDOW_SAMPLES)), 0.0)

    def test_no_bundled_whisper_model_does_not_download(self):
        with self.assertRaises(WakeModelUnavailable):
            load_local_whisper(bundled_model=None)
        with self.assertRaises(WakeModelUnavailable):
            load_local_whisper(bundled_model="/definitely/missing/faster-whisper-model")

    def test_custom_model_only_mode_does_not_fallback_to_noncommercial_oww(self):
        from unittest.mock import patch
        from wake_word import openwakeword
        with patch.dict("os.environ", {"JARVIS_WAKE_ENGINE": "whisper_local"}):
            with patch("wake_word.whisper_local_wake.load_local_whisper",
                       side_effect=WakeModelUnavailable("missing")):
                with patch.object(openwakeword, "BuiltinInference",
                                  side_effect=AssertionError("forbidden fallback")):
                    with self.assertRaises(WakeModelUnavailable):
                        openwakeword._build_recognizer()


if __name__ == "__main__":
    unittest.main()
