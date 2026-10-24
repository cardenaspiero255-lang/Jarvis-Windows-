"""RED contract for genuine local ASR inference measurement on Windows SAPI WAVs."""
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

from real_whisper_local_windows import measure_cases, read_wav_pcm16


class RealWhisperLocalMeasurementTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def audio(self, name):
        p = self.root / name
        samples = np.tile(np.array([2400, -2400], dtype="<i2"), 16000)
        with wave.open(str(p), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(samples.tobytes())
        return p

    def test_read_genuine_pcm_frames_and_reject_wrong_rate(self):
        p = self.audio("positive.wav")
        self.assertEqual(read_wav_pcm16(p).shape, (32000,))
        with wave.open(str(p), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(8000)
            w.writeframes(b"\x01\x00" * 16000)
        with self.assertRaises(ValueError):
            read_wav_pcm16(p)

    def test_measured_real_clip_receipts_cannot_claim_human_positives(self):
        pos, neg = self.audio("pos.wav"), self.audio("neg.wav")
        class Fake:
            key = "fake"
            def __init__(self):
                self.n = 0
            def predict(self, frame):
                self.n += 1
                return 1.0 if self.n == 36 else 0.0
            def reset(self):
                self.n = 0
        report = measure_cases([
            {"file": pos.name, "label": "synthetic_positive"},
            {"file": neg.name, "label": "synthetic_negative"},
        ], self.root, detector_factory=Fake)
        self.assertEqual(report["status"], "MEASURED_SYNTHETIC_ONLY_NOT_CERTIFIED")
        self.assertEqual(report["synthetic_positive_count"], 1)
        self.assertEqual(report["synthetic_negative_count"], 1)
        self.assertEqual(report["positive_triggered"], 1)
        self.assertEqual(report["negative_false_activations"], 1)
        self.assertEqual(report["independent_human_positive_count"], 0)
        self.assertFalse(report["offline_installer_certified"])
        self.assertFalse(report["physical_microphone_certified"])

    def test_reject_duplicate_labels_and_file_traversal(self):
        p = self.audio("pos.wav")
        with self.assertRaises(ValueError):
            measure_cases([{"file": "../pos.wav", "label": "synthetic_positive"}],
                          self.root, detector_factory=lambda: None)
        with self.assertRaises(ValueError):
            measure_cases([{"file": p.name, "label": "human_positive"}],
                          self.root, detector_factory=lambda: None)

    def test_reject_silent_audio_for_positive_diagnostic(self):
        p = self.root / "empty.wav"
        with wave.open(str(p), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(b"\x00\x00" * 16000)
        with self.assertRaises(ValueError):
            measure_cases([{"file": p.name, "label": "synthetic_positive"}],
                          self.root, detector_factory=lambda: None)


if __name__ == "__main__":
    unittest.main()
