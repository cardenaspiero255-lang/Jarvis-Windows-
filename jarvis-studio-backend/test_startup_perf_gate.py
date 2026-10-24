"""Fail-closed real-Windows startup benchmark rules (red before implementation)."""
import unittest
from startup_perf_gate import assess_windows_lite_samples, STARTUP_BUDGET


def sample(**override):
    defaults = {
        "environment": "github_hosted_windows",
        "profile_simulated_ram_gib": 4,
        "model_loaded": True,
        "piper_preloaded": False,
        "whisper_ready_ms": 14000,
        "full_worker_ms": 16500,
        "peak_rss_mib": 510.0,
        "model_sha256": "a" * 64,
        "model_revision": "b" * 40,
    }
    return {**defaults, **override}


class LiteStartupGateTests(unittest.TestCase):
    def test_three_independent_real_processes_pass_with_fixed_limits(self):
        out = assess_windows_lite_samples([
            sample(), sample(whisper_ready_ms=21000, full_worker_ms=24500, peak_rss_mib=600),
            sample(whisper_ready_ms=17500, full_worker_ms=20500, peak_rss_mib=570)
        ])
        self.assertEqual(out["status"], "LITE_STARTUP_WIN_CI_PASS")
        self.assertEqual(out["trials"], 3)
        self.assertEqual(out["peak_rss_mib_observed"], 600)
        self.assertEqual(out["whisper_ready_p95_ms"], 21000)
        self.assertFalse(out["four_gib_physical_certified"])
        self.assertFalse(out["complete_gui_startup_certified"])

    def test_a_model_cannot_finish_after_its_process_exited(self):
        # A fabricated early-worker-exit observation is invalid rather than a
        # memory or latency regression. This was the cause of CI's fixture fail.
        out = assess_windows_lite_samples([
            sample(), sample(whisper_ready_ms=21000, full_worker_ms=16500),
            sample(),
        ])
        self.assertEqual(out["status"], "NOT_CERTIFIED")
        self.assertIn("timing_inconsistent", out["blockers"])

    def test_one_slow_run_blocks_p95_instead_of_hiding_it_in_median(self):
        cases = [sample(),sample(),sample(whisper_ready_ms=STARTUP_BUDGET["whisper_ready_p95_ms"]+1,
                                         full_worker_ms=STARTUP_BUDGET["whisper_ready_p95_ms"]+2)]
        self.assertEqual(assess_windows_lite_samples(cases)["status"], "NOT_CERTIFIED")

    def test_memory_peak_above_budget_blocks(self):
        self.assertEqual(assess_windows_lite_samples([
            sample(),sample(),sample(peak_rss_mib=STARTUP_BUDGET["peak_rss_mib"]+1)
        ])["status"], "NOT_CERTIFIED")

    def test_missing_or_faked_inference_never_passes(self):
        for change in (
            {"model_loaded": False}, {"piper_preloaded": True},
            {"environment": "synthetic_linux"}, {"model_sha256": ""},
            {"model_revision": "main"}, {"profile_simulated_ram_gib": 8},
            {"peak_rss_mib": float("nan")}, {"whisper_ready_ms": -1},
        ):
            with self.subTest(change=change):
                self.assertEqual(
                    assess_windows_lite_samples([sample(**change)] + [sample(),sample()])["status"],
                    "NOT_CERTIFIED",
                )

    def test_three_trial_minimum_and_same_asset_revision_required(self):
        self.assertEqual(assess_windows_lite_samples([sample(),sample()])["status"],
                         "NOT_CERTIFIED")
        self.assertEqual(assess_windows_lite_samples([
            sample(),sample(),sample(model_sha256="c"*64)
        ])["status"], "NOT_CERTIFIED")

    def test_real_faster_whisper_model_has_all_required_vocab_assets(self):
        # Regression: a config+model.bin+tokenizer-only snapshot passed the
        # superficial asset check but CTranslate2 could not load its vocabulary.
        from windows_startup_perf import REQUIRED_MODEL_FILES, MODEL_FETCH_PATTERNS
        self.assertIn("vocabulary.txt", REQUIRED_MODEL_FILES)
        self.assertTrue(set(REQUIRED_MODEL_FILES).issubset(set(MODEL_FETCH_PATTERNS)))

    def test_reject_unauthorised_budget_overrides(self):
        with self.assertRaises(TypeError):
            assess_windows_lite_samples([sample()]*3, memory_budget_mib=5000)


if __name__ == "__main__":
    unittest.main()
