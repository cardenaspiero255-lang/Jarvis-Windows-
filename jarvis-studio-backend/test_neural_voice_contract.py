"""Fail-closed model verdict policies: not virtual audio device certification."""
import unittest
from neural_voice_contract import piper_verdict, wake_verdict


class PiperVerdictTests(unittest.TestCase):
    def setUp(self):
        self.clips = [{"sample_rate": 22050, "duration_s": 1.7, "rms": 1100,
                       "peak": 9000, "channels": 1, "sample_width": 2}] * 3

    def test_three_genuine_non_silent_wave_observations_required(self):
        self.assertEqual(piper_verdict(self.clips), "PIPER_SYNTHESIS_PASS")
        self.assertEqual(piper_verdict(self.clips[:2]), "NOT_CERTIFIED")
        self.assertEqual(piper_verdict([dict(self.clips[0], rms=0)] * 3),
                         "NOT_CERTIFIED")
        self.assertEqual(piper_verdict([dict(self.clips[0], channels=2)] * 3),
                         "NOT_CERTIFIED")
        self.assertEqual(piper_verdict([dict(self.clips[0], duration_s=0.01)] * 3),
                         "NOT_CERTIFIED")


class WakeVerdictTests(unittest.TestCase):
    def test_positive_and_negative_model_scores_gate_at_runtime_threshold(self):
        self.assertEqual(wake_verdict([0.6, 0.1], [0.02, 0.03], 0, 0.4),
                         "WAKE_ACOUSTIC_PASS")
        self.assertEqual(wake_verdict([0.39, 0.1], [0.02, 0.03], 0, 0.4),
                         "NOT_CERTIFIED")
        self.assertEqual(wake_verdict([0.6, 0.1], [0.02, 0.43], 0, 0.4),
                         "NOT_CERTIFIED")
        self.assertEqual(wake_verdict([0.6, 0.1], [0.02, 0.03], 0.4, 0.4),
                         "NOT_CERTIFIED")
        self.assertEqual(wake_verdict([0.6, float("nan")], [0, 0], 0, 0.4),
                         "NOT_CERTIFIED")
        self.assertEqual(wake_verdict([], [], 0, 0.4), "NOT_CERTIFIED")


if __name__ == "__main__":
    unittest.main()
