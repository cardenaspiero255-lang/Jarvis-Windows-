"""Adversarial voice pipeline regression with injected audio-device failures.

These checks are not a substitute for physical hardware certification.
"""
import asyncio
import unittest
from unittest import mock

import numpy as np

import main
from transcription import whisper_transcriber as transcriber


class WakeFalsePositiveSecondStage(unittest.IsolatedAsyncioTestCase):
    async def test_wake_model_jarvis_only_false_positive_does_not_make_command(self):
        clip = np.zeros(1280, dtype=np.int16)
        with mock.patch.object(
            main, "transcribe_clip", new_callable=mock.AsyncMock,
            return_value="Jarvis is a digital assistant created for computers."
        ) as transcribe:
            command = await main._command_from_clip(clip, speech=True)
        self.assertEqual(command, "")
        transcribe.assert_awaited_once()

    async def test_only_real_hey_jarvis_phrase_can_become_a_command(self):
        clip = np.ones(1280, dtype=np.int16)
        with mock.patch.object(
            main, "transcribe_clip", new_callable=mock.AsyncMock,
            return_value="Hey Jarvis, open my calendar."
        ):
            command = await main._command_from_clip(clip, speech=True)
        self.assertEqual(command, "open my calendar.")


class HardStopRevocation(unittest.IsolatedAsyncioTestCase):
    async def test_stop_trips_interrupt_mic_tts_disarms_controls_and_emits_idle(self):
        event = asyncio.Event()
        tts = mock.Mock()
        with mock.patch.object(main, "_interrupt", event), \
             mock.patch.object(main, "_tts", tts), \
             mock.patch.object(main, "emit", new_callable=mock.AsyncMock) as emit, \
             mock.patch.object(main.computer, "disarm") as disarm, \
             mock.patch.object(transcriber, "request_cancel") as cancel:
            await main.handle_stop_speech({})
        self.assertTrue(event.is_set())
        tts.stop.assert_called_once()
        disarm.assert_called_once()
        cancel.assert_called_once()
        emit.assert_awaited_with("status", "idle")


class PortAudioRecovery(unittest.TestCase):
    def setUp(self):
        transcriber._cancel_listen.clear()
        transcriber._finish_listen.clear()
        transcriber._ptt_mode.clear()

    def tearDown(self):
        transcriber._cancel_listen.clear()
        transcriber._finish_listen.clear()
        transcriber._ptt_mode.clear()

    def test_failed_device_open_does_not_poison_next_recording(self):
        first = mock.Mock()
        first.open.side_effect = OSError("access denied")
        second = mock.Mock()
        stream = mock.Mock()
        second.open.return_value = stream
        count = [0]
        def read_chunk(size, **kwargs):
            count[0] += 1
            if count[0] == 5:
                transcriber.request_finish()
            return np.full(size, 6000, dtype=np.int16).tobytes()
        stream.read.side_effect = read_chunk
        with mock.patch.object(transcriber.pyaudio, "PyAudio", side_effect=[first, second]):
            with self.assertRaises(OSError):
                transcriber._record_until_silence()
            transcriber.set_ptt(True)
            audio = transcriber._record_until_silence()
        first.terminate.assert_called_once()
        stream.stop_stream.assert_called_once()
        stream.close.assert_called_once()
        second.terminate.assert_called_once()
        self.assertEqual(audio.size, 5 * transcriber.CHUNK_SIZE)
        self.assertFalse(transcriber._ptt_mode.is_set())


if __name__ == "__main__":
    unittest.main()
