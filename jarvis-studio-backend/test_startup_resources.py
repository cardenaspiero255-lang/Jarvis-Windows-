"""Low-RAM Windows startup policy and sequential warm-up regressions (TDD)."""
import unittest
from unittest import mock

from startup_resources import choose_plan, warm_voice_models, get_windows_memory_bytes


GIB = 1024 ** 3


class MemoryAwareStartupPlanTests(unittest.TestCase):
    def test_four_gib_notebook_does_not_eager_load_piper_and_whisper_together(self):
        plan = choose_plan(total_bytes=4*GIB, available_bytes=2*GIB,
                           use_text=False, requested="auto")
        self.assertEqual(plan.mode, "lite")
        self.assertTrue(plan.whisper)
        self.assertFalse(plan.tts)

    def test_low_free_memory_skips_both_eager_loads_to_avoid_pressure(self):
        plan = choose_plan(total_bytes=8*GIB, available_bytes=700*1024**2,
                           use_text=False, requested="auto")
        self.assertEqual(plan.mode, "lite")
        self.assertFalse(plan.whisper)
        self.assertFalse(plan.tts)

    def test_text_only_mode_does_not_warm_unneeded_local_stt(self):
        plan = choose_plan(total_bytes=16*GIB, available_bytes=9*GIB,
                           use_text=True, requested="auto")
        self.assertEqual(plan.mode, "normal")
        self.assertFalse(plan.whisper)
        self.assertTrue(plan.tts)

    def test_normal_profile_sequentially_warms_both_models(self):
        plan = choose_plan(total_bytes=16*GIB, available_bytes=9*GIB,
                           use_text=False, requested="auto")
        self.assertEqual(plan.mode, "normal")
        self.assertTrue(plan.whisper)
        self.assertTrue(plan.tts)

    def test_explicit_lite_override_requires_no_memory_probe(self):
        plan = choose_plan(total_bytes=None, available_bytes=None,
                           use_text=False, requested="lite")
        self.assertEqual(plan.mode, "lite")
        self.assertFalse(plan.tts)

    def test_invalid_override_does_not_force_eager_memory_usage(self):
        plan = choose_plan(total_bytes=4*GIB, available_bytes=2*GIB,
                           use_text=False, requested="bogus")
        self.assertEqual(plan.mode, "lite")

    def test_absent_windows_memory_api_has_no_forged_readings(self):
        with mock.patch("startup_resources.sys.platform", "linux"):
            self.assertIsNone(get_windows_memory_bytes())


class SequentialWarmupTests(unittest.IsolatedAsyncioTestCase):
    async def test_never_runs_whisper_and_tts_in_parallel(self):
        events = []
        async def whisper():
            events.extend(("whisper_start", "whisper_end"))
        async def tts():
            events.extend(("tts_start", "tts_end"))
        plan = choose_plan(total_bytes=16*GIB, available_bytes=9*GIB,
                           use_text=False, requested="auto")
        await warm_voice_models(plan, whisper, tts)
        self.assertEqual(events, ["whisper_start", "whisper_end",
                                  "tts_start", "tts_end"])

    async def test_warmup_failure_does_not_prevent_next_backend(self):
        events = []
        async def whisper():
            events.append("whisper")
            raise RuntimeError("offline local model")
        async def tts():
            events.append("tts")
        plan = choose_plan(total_bytes=16*GIB, available_bytes=9*GIB,
                           use_text=False, requested="normal")
        result = await warm_voice_models(plan, whisper, tts)
        self.assertEqual(events, ["whisper", "tts"])
        self.assertEqual(result["whisper"], "unavailable")
        self.assertEqual(result["tts"], "ready")

    async def test_low_ram_only_warms_whisper(self):
        whisper = mock.AsyncMock()
        tts = mock.AsyncMock()
        plan = choose_plan(total_bytes=4*GIB, available_bytes=2*GIB,
                           use_text=False, requested="auto")
        result = await warm_voice_models(plan, whisper, tts)
        whisper.assert_awaited_once()
        tts.assert_not_awaited()
        self.assertEqual(result["tts"], "deferred")


if __name__ == "__main__":
    unittest.main()
