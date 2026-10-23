"""Independent real-human accent corpus contract, never re-label by model score."""
import copy
import unittest

from wake_independent_corpus import (
    FROZEN_NEGATIVE_MANIFEST, REQUIRED_SOURCE_COMMIT,
    validate_manifest, adjudicate_negative_scores,
)


class FreezeIndependentSources(unittest.TestCase):
    def test_manifest_is_speaker_disjoint_real_recordings_with_at_least_four_accents(self):
        cases = FROZEN_NEGATIVE_MANIFEST
        self.assertGreaterEqual(len(cases), 6)
        self.assertEqual(validate_manifest(cases), [])
        self.assertEqual(len({c["speaker"] for c in cases}), len(cases))
        self.assertGreaterEqual(len({c["accent"] for c in cases}), 4)
        self.assertTrue(all(c["label"] == "no_hey_jarvis" for c in cases))
        self.assertTrue(all(c["source_kind"] == "recorded_human" for c in cases))
        self.assertTrue(all(c["license"] == "CC0-1.0" for c in cases))
        self.assertTrue(all(c["source_commit"] == REQUIRED_SOURCE_COMMIT for c in cases))
        self.assertTrue(all(c["source_path"].startswith("voices/") and
                            c["source_path"].endswith(".flac") for c in cases))
        self.assertTrue(all(len(c["git_blob_sha"]) == 40 for c in cases))

    def test_reject_forged_or_leaky_sources_before_any_model_inference(self):
        cases = copy.deepcopy(FROZEN_NEGATIVE_MANIFEST)
        for key, value in (
            ("source_commit", "main"), ("source_kind", "sapi_synthetic"),
            ("license", "unknown"), ("git_blob_sha", "0"),
            ("speaker", cases[1]["speaker"]), ("label", "positive"),
            ("accent", ""), ("source_path", "../rogue.flac"),
        ):
            with self.subTest(key=key):
                modified = copy.deepcopy(cases)
                modified[0][key] = value
                self.assertNotEqual(validate_manifest(modified), [])
        self.assertNotEqual(validate_manifest(cases[:3]), [])

    def test_results_fail_closed_without_six_complete_independent_scores(self):
        cases = FROZEN_NEGATIVE_MANIFEST
        values = {c["speaker"]: 0.02 for c in cases}
        self.assertEqual(
            adjudicate_negative_scores(cases, values, 0.4)["status"],
            "NEGATIVE_HUMAN_CORPUS_PASS",
        )
        corrupted = dict(values)
        corrupted[cases[0]["speaker"]] = 0.4
        self.assertEqual(
            adjudicate_negative_scores(cases, corrupted, 0.4)["status"],
            "NOT_CERTIFIED",
        )
        corrupted[cases[0]["speaker"]] = 0.99
        self.assertEqual(
            adjudicate_negative_scores(cases, corrupted, 0.4)["status"],
            "NOT_CERTIFIED",
        )
        corrupted[cases[0]["speaker"]] = float("nan")
        self.assertEqual(
            adjudicate_negative_scores(cases, corrupted, 0.4)["status"],
            "NOT_CERTIFIED",
        )
        self.assertEqual(
            adjudicate_negative_scores(cases, {}, 0.4)["status"],
            "NOT_CERTIFIED",
        )
        self.assertEqual(
            adjudicate_negative_scores(cases, values, 0.6)["status"],
            "NOT_CERTIFIED",  # never raise the threshold to manufacture green
        )

    def test_never_mix_independent_human_negatives_with_sapi_positive_claims(self):
        result = adjudicate_negative_scores(
            FROZEN_NEGATIVE_MANIFEST,
            {c["speaker"]: 0.01 for c in FROZEN_NEGATIVE_MANIFEST}, 0.4,
        )
        self.assertFalse(result["independent_positive_corpus_certified"])
        self.assertFalse(result["physical_microphone_certified"])
        self.assertFalse(result["entire_wake_acoustic_gate_certified"])


if __name__ == "__main__":
    unittest.main()
