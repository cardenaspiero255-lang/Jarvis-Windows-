"""Regressions: acoustic false wakes cannot raise UI before Whisper confirmation."""
import asyncio
import unittest
from unittest import mock

import numpy as np

import main


class FakeWakeDetector:
    capture_commands = True

    def __init__(self):
        self.fired = False
        self.started = 0
        self.stopped = 0

    def on_detected(self, callback):
        self.wake_callback = callback

    def on_command(self, callback):
        self.clip_callback = callback

    def start(self):
        self.started += 1
        if not self.fired:
            self.fired = True
            self.wake_callback()
            # The real detector records for seconds AFTER acoustic wake.
            # _wake_clip intentionally drains clips from abandoned turns
            # before awaiting this turn. Delivering a fake clip before the
            # waiter starts would be stale and cause a 25-second timeout.
            asyncio.get_running_loop().call_later(
                0.08,
                lambda: self.clip_callback(np.zeros(16000, dtype=np.int16), True),
            )

    def stop(self):
        self.stopped += 1


class ConfirmBeforeWakeUI(unittest.IsolatedAsyncioTestCase):
    async def _run_clip(self, transcript, *, real_command):
        detector = FakeWakeDetector()
        events = []
        terminal = asyncio.Event()
        async def emitted(name, data):
            events.append((name, data))
            if (not real_command and name == "status" and data == "idle"
                    and sum(e == ("status", "idle") for e in events) >= 2):
                terminal.set()
        async def pipeline(text, **kwargs):
            terminal.set()

        patches = [
            mock.patch.object(main, "_always_on_event", None),
            mock.patch.object(main, "_trigger_listen", asyncio.Event()),
            mock.patch.object(main, "_interrupt", asyncio.Event()),
            mock.patch.object(main, "get_model", return_value="local"),
            mock.patch.object(main.gemini_bridge, "is_native_audio_model", return_value=False),
            mock.patch.object(main, "transcribe_clip", new_callable=mock.AsyncMock,
                              return_value=transcript),
            mock.patch.object(main, "emit", new=emitted),
            mock.patch.object(main, "_run_pipeline", new=pipeline),
        ]
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
            task = asyncio.create_task(main.wake_word_loop(detector))
            try:
                await asyncio.wait_for(terminal.wait(), timeout=8)
                await asyncio.sleep(0)
            finally:
                task.cancel()
                await asyncio.wait_for(task, timeout=3)
        return events

    async def test_acoustic_jarvis_mention_without_hey_never_opens_wake_ui(self):
        events = await self._run_clip(
            "Jarvis is a digital assistant created for computers.",
            real_command=False)
        self.assertNotIn(("wake_triggered", True), events)
        self.assertNotIn(("status", "listening"), events)
        self.assertIn(("status", "idle"), events)

    async def test_acoustic_hey_travis_never_opens_wake_ui(self):
        events = await self._run_clip(
            "Hey Travis, open my calendar.", real_command=False)
        self.assertNotIn(("wake_triggered", True), events)
        self.assertNotIn(("status", "listening"), events)
        self.assertIn(("status", "idle"), events)

    async def test_whisper_jervis_spelling_still_opens_wake_ui(self):
        events = await self._run_clip(
            "Hey Jervis, open my calendar.", real_command=True)
        self.assertIn(("wake_triggered", True), events)
        self.assertIn(("status", "listening"), events)

    async def test_true_wake_still_opens_ui_and_is_processed(self):
        events = await self._run_clip(
            "Hey Jarvis, open my calendar.", real_command=True)
        self.assertIn(("wake_triggered", True), events)
        self.assertIn(("status", "listening"), events)


if __name__ == "__main__":
    unittest.main()
