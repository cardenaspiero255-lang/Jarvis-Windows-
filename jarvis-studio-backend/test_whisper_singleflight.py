"""Regression: concurrent preload and wake inference must share one model."""
import concurrent.futures
import threading
import time
import unittest
from unittest import mock

from transcription import whisper_transcriber as tr


class WhisperSingleFlight(unittest.TestCase):
    def setUp(self):
        self.previous = tr._model
        tr._model = None

    def tearDown(self):
        tr._model = self.previous

    def test_concurrent_first_wake_and_boot_warmup_construct_only_one_model(self):
        constructing = threading.Event()
        release = threading.Event()
        constructor_count = []
        fake_model = object()

        def constructor(*args, **kwargs):
            constructor_count.append(1)
            constructing.set()
            release.wait(timeout=2)
            return fake_model

        with mock.patch.object(tr, "WhisperModel", side_effect=constructor), \
             mock.patch.object(tr, "_bundled_model_path", return_value=None):
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(tr._get_model)
                self.assertTrue(constructing.wait(timeout=2))
                second = pool.submit(tr._get_model)
                time.sleep(0.15)  # old code races into a second construction here
                release.set()
                self.assertIs(first.result(timeout=3), fake_model)
                self.assertIs(second.result(timeout=3), fake_model)
        self.assertEqual(len(constructor_count), 1)

    def test_construction_failure_does_not_poison_later_retry(self):
        calls = [0]
        fake_model = object()
        def factory(*args, **kwargs):
            calls[0] += 1
            if calls[0] == 1:
                raise RuntimeError("model asset not provisioned")
            return fake_model
        with mock.patch.object(tr, "WhisperModel", side_effect=factory), \
             mock.patch.object(tr, "_bundled_model_path", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "not provisioned"):
                tr._get_model()
            self.assertIs(tr._get_model(), fake_model)
        self.assertEqual(calls[0], 2)


if __name__ == "__main__":
    unittest.main()
