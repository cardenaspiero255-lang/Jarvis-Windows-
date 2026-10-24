"""Adversarial contracts for blind-comparison data and honest FPR/FNR claims."""
import copy
import unittest

from wake_hard_benchmark import (
    FROZEN_SAMPLES, SOURCE_COMMIT, PRODUCTION_THRESHOLD, validate_manifest,
    score_negative_comparison, classification_metrics, verify_real_positive_intake,
)


class TestFreezeBeforeModelPredictions(unittest.TestCase):
    def test_wake_near_misses_are_real_recordings_but_never_hey_jarvis_positives(self):
        samples = FROZEN_SAMPLES
        self.assertEqual(validate_manifest(samples), [])
        self.assertEqual(len(samples), 16)
        self.assertEqual(len({r["git_blob_sha"] for r in samples}), 16)
        self.assertEqual(len({r["source_path"] for r in samples}), 16)
        self.assertEqual(sum(r["split"] == "development" for r in samples), 8)
        self.assertEqual(sum(r["split"] == "holdout" for r in samples), 8)
        self.assertEqual(sum(r["phrase"] == "jarvis" for r in samples), 12)
        self.assertEqual(sum(r["phrase"] == "computer" for r in samples), 2)
        self.assertEqual(sum(r["phrase"] == "alexa" for r in samples), 2)
        self.assertTrue(all(r["label"] == "hard_negative" for r in samples))
        self.assertTrue(all(r["source_commit"] == SOURCE_COMMIT for r in samples))
        self.assertTrue(all(r["source_kind"] == "human_recording" for r in samples))
        self.assertTrue(all(r["license"] == "Apache-2.0" for r in samples))

    def test_prevent_relabeling_jarvis_as_hey_jarvis_and_duplicate_partitions(self):
        for key, wrong in (
            ("source_commit", "master"),
            ("label", "positive"),
            ("source_kind", "synthetic"),
            ("git_blob_sha", "deadbeef"),
            ("license", "unknown"),
            ("split", "train"),
            ("source_path", "../evil.wav"),
        ):
            with self.subTest(key=key):
                rows = copy.deepcopy(FROZEN_SAMPLES)
                rows[0][key] = wrong
                self.assertNotEqual(validate_manifest(rows), [])
        rows = copy.deepcopy(FROZEN_SAMPLES)
        rows[8]["source_path"] = rows[0]["source_path"]
        self.assertNotEqual(validate_manifest(rows), [])

    def test_same_threshold_scores_real_baseline_vs_secondary_verifier(self):
        baseline = [0.51, 0.03, 0.72, 0.08]
        verified = [False, False, False, False]
        report = score_negative_comparison(baseline, verified, 0.4)
        self.assertEqual(report["baseline_false_activations"], 2)
        self.assertEqual(report["verified_false_activations"], 0)
        self.assertEqual(report["evaluated_clips"], 4)
        self.assertFalse(report["false_reject_rate_certified"])
        self.assertFalse(report["speaker_independent_certified"])
        self.assertFalse(report["positive_human_corpus_certified"])

    def test_verifier_may_not_invent_baseline_triggers_or_override_threshold(self):
        for scores, verdicts, threshold in (
            ([0.02], [True], 0.4),
            ([0.42], [True], 0.65),
            ([float("nan")], [False], 0.4),
            ([0.8, 0.2], [False], 0.4),
        ):
            with self.subTest(scores=scores, threshold=threshold):
                self.assertEqual(
                    score_negative_comparison(scores, verdicts, threshold)["status"],
                    "NOT_CERTIFIED",
                )

    def test_no_positive_recall_when_no_real_hey_jarvis_positive_observed(self):
        metrics = classification_metrics(negatives=4, baseline_fp=2, verified_fp=0,
                                         real_positives=0, baseline_tp=0, verified_tp=0)
        self.assertIsNone(metrics["baseline_fnr"])
        self.assertIsNone(metrics["verified_fnr"])
        self.assertEqual(metrics["baseline_fpr_per_clip"], 0.5)
        self.assertEqual(metrics["verified_fpr_per_clip"], 0.0)
        self.assertFalse(metrics["false_alarms_per_hour_certified"])

    def test_positive_intake_requires_consent_hash_audio_phrase_and_speaker_disjoint(self):
        intake = [{
            "clip_sha256": "a" * 64, "speaker_id": "speaker_a",
            "phrase": "hey jarvis", "source_kind": "recorded_human",
            "consent": "explicit_research_use", "source_set": "new_collection",
            "split": "development", "license": "CC0-1.0",
            "verification": "human_audio_and_transcript_review",
        }, {
            "clip_sha256": "b" * 64, "speaker_id": "speaker_b",
            "phrase": "hey jarvis", "source_kind": "recorded_human",
            "consent": "explicit_research_use", "source_set": "new_collection",
            "split": "holdout", "license": "CC0-1.0",
            "verification": "human_audio_and_transcript_review",
        }]
        self.assertEqual(verify_real_positive_intake(intake), [])
        bad = copy.deepcopy(intake)
        bad[0]["source_kind"] = "sapi"
        self.assertNotEqual(verify_real_positive_intake(bad), [])
        bad = copy.deepcopy(intake)
        bad[1]["speaker_id"] = bad[0]["speaker_id"]
        self.assertNotEqual(verify_real_positive_intake(bad), [])
        bad = copy.deepcopy(intake)
        bad[1]["phrase"] = "jarvis"
        self.assertNotEqual(verify_real_positive_intake(bad), [])


if __name__ == "__main__":
    unittest.main()
