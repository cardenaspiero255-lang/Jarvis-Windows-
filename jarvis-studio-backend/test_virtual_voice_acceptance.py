"""TDD: offline Windows synthesized WAV -> real JARVIS voice path contract.

These tests do not impersonate a physical microphone or loudspeaker.
"""
from __future__ import annotations

import io
import unittest
import wave
from unittest import mock

import numpy as np

from virtual_voice_acceptance import decode_wave, evaluate_transcripts


def wav_bytes(samples, *, rate=16000, channels=1):
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.asarray(samples, dtype="<i2").tobytes())
    return out.getvalue()


class VirtualWaveAcceptanceTests(unittest.TestCase):
    def test_valid_real_pcm_wave_yields_exact_16k_samples(self):
        samples = (np.sin(np.linspace(0, 500, 16000)) * 13000).astype(np.int16)
        pcm, details = decode_wave(wav_bytes(samples))
        np.testing.assert_array_equal(pcm, samples)
        self.assertGreater(details["rms"], 1000)
        self.assertEqual(details["sample_rate"], 16000)
        self.assertEqual(details["duration_seconds"], 1.0)

    def test_silence_and_truncated_wave_fail_closed(self):
        for bad in (wav_bytes(np.zeros(16000, dtype=np.int16)),
                    wav_bytes(np.ones(1000, dtype=np.int16) * 9000),
                    b"not a wav", b""):
            with self.subTest(length=len(bad)):
                with self.assertRaises(ValueError):
                    decode_wave(bad)

    def test_wrong_rate_stereo_and_format_do_not_claim_16k_audio(self):
        for raw in (wav_bytes(np.ones(16000, dtype=np.int16) * 3000, rate=8000),
                    wav_bytes(np.ones(32000, dtype=np.int16) * 3000, channels=2)):
            with self.subTest(length=len(raw)):
                with self.assertRaises(ValueError):
                    decode_wave(raw)

    def test_real_transcription_acceptance_requires_wake_and_separate_negative(self):
        good = evaluate_transcripts(
            "Hey Jarvis, what time is it?", "The quick brown fox jumps over the lazy dog."
        )
        self.assertEqual(good["status"], "VIRTUAL_STT_WAKE_PASS")
        self.assertFalse(good["physical_microphone_certified"])
        self.assertFalse(good["jarvis_tts_certified"])
        self.assertEqual(good["wake_command"], "what time is it?")

    def test_false_wake_empty_command_and_hallucinated_silence_rejected(self):
        for wake, normal in (
            ("Jarvis is a digital assistant.", "A sunny day."),
            ("Hey Jarvis", "The quick brown fox."),
            ("Hey Jarvis, tell me the time", "Hey Jarvis, tell me the weather."),
            ("thank you for watching", "The quick brown fox."),
        ):
            with self.subTest(wake=wake, normal=normal):
                report = evaluate_transcripts(wake, normal)
                self.assertEqual(report["status"], "NOT_CERTIFIED")
                self.assertFalse(report["physical_microphone_certified"])


class VirtualMicrophoneCancellationTests(unittest.TestCase):
    def setUp(self):
        from transcription import whisper_transcriber as tr
        self.tr = tr
        tr._cancel_listen.clear()
        tr._finish_listen.clear()
        tr._ptt_mode.clear()

    def tearDown(self):
        self.tr._cancel_listen.clear()
        self.tr._finish_listen.clear()
        self.tr._ptt_mode.clear()

    def test_stop_drops_pending_pcm_without_late_transcription(self):
        tr = self.tr
        pa = mock.Mock()
        mic = mock.Mock()
        pa.open.return_value = mic
        calls = [0]

        def feed(count, **kwargs):
            calls[0] += 1
            if calls[0] == 3:
                tr.request_cancel()
            return (np.ones(count, dtype="<i2") * 4000).tobytes()

        mic.read.side_effect = feed
        with mock.patch.object(tr.pyaudio, "PyAudio", return_value=pa):
            audio = tr._record_until_silence()
        self.assertEqual(audio.size, 0)
        self.assertTrue(mic.stop_stream.called)
        self.assertTrue(mic.close.called)
        self.assertTrue(pa.terminate.called)

    def test_finishing_push_to_talk_keeps_captured_frames(self):
        tr = self.tr
        pa = mock.Mock()
        mic = mock.Mock()
        pa.open.return_value = mic
        reads = [0]

        def feed(count, **kwargs):
            reads[0] += 1
            if reads[0] == 4:
                tr.request_finish()
            return (np.ones(count, dtype="<i2") * 4000).tobytes()

        mic.read.side_effect = feed
        tr.set_ptt(True)
        with mock.patch.object(tr.pyaudio, "PyAudio", return_value=pa):
            audio = tr._record_until_silence()
        self.assertGreater(audio.size, 0)
        self.assertEqual(audio.size, 4 * tr.CHUNK_SIZE)
        self.assertFalse(tr._ptt_mode.is_set())

    def test_denied_microphone_frees_pyaudio_adapter(self):
        tr = self.tr
        pa = mock.Mock()
        pa.open.side_effect = OSError("permission denied")
        with mock.patch.object(tr.pyaudio, "PyAudio", return_value=pa):
            with self.assertRaises(OSError):
                tr._record_until_silence()
        pa.terminate.assert_called_once()


if __name__ == "__main__":
    unittest.main()
