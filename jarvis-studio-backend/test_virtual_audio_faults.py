"""Adversarial audio tests: real cancellation windows and WAV cleanup.

The tests intentionally fail against the pre-fix code and use no microphone.
"""
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from tts.tts_engine import TTSEngine
from transcription import whisper_transcriber as mic


class EarlyStopDuringDeviceOpen(unittest.TestCase):
    def setUp(self):
        mic._cancel_listen.clear()
        mic._finish_listen.clear()
        mic._ptt_mode.clear()

    def tearDown(self):
        mic._cancel_listen.clear()
        mic._finish_listen.clear()
        mic._ptt_mode.clear()

    def test_cancel_during_device_open_must_not_get_cleared(self):
        """GUI STOP may arrive while PortAudio blocks opening the device."""
        pya = mock.Mock()
        stream = mock.Mock()
        stream.read.side_effect = lambda count, **kw: np.full(
            count, 2000, dtype=np.int16).tobytes()
        def opening(**kw):
            mic.request_cancel()
            return stream
        pya.open.side_effect = opening
        with mock.patch.object(mic.pyaudio, "PyAudio", return_value=pya):
            audio = mic._record_until_silence()
        self.assertEqual(len(audio), 0)
        stream.read.assert_not_called()
        stream.stop_stream.assert_called_once()
        stream.close.assert_called_once()
        pya.terminate.assert_called_once()


class PiperSynthesisInterruption(unittest.IsolatedAsyncioTestCase):
    async def test_failed_synthesis_does_not_leak_temporary_wave(self):
        """A Piper ONNX failure after mkstemp must clean up the allocated file."""
        voice = mock.Mock()
        def abort_after_header(text, writer):
            # Real Piper fills the WAV metadata before emitting audio.
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(22050)
            raise RuntimeError("inference_aborted")
        voice.synthesize_wav.side_effect = abort_after_header
        engine = TTSEngine.__new__(TTSEngine)
        engine._ensure_piper = mock.Mock(return_value=voice)
        engine._stopped = False
        engine._play_file = mock.AsyncMock()
        real_mkstemp = tempfile.mkstemp
        with tempfile.TemporaryDirectory() as root, mock.patch(
            "tts.tts_engine.tempfile.mkstemp",
            side_effect=lambda suffix: real_mkstemp(suffix=suffix, dir=root)
        ):
            with self.assertRaisesRegex(RuntimeError, "inference_aborted"):
                await engine._speak_piper("Test voice synthesis failure.")
            self.assertEqual(list(Path(root).glob("*.wav")), [])
        engine._play_file.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
