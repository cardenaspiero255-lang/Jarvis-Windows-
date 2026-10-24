"""RED contracts for reproducible synthetic voice stress (not human certification)."""
import copy
import hashlib
import json
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

from synthetic_wake_stress import (
    VARIANTS, frozen_threshold, validate_manifest, perturb_pcm,
    synthetic_metrics, summarize_experiment, compare_prompt_strategies,
)


def fixture(root: Path, *, profile="smoke"):
    cases = []
    count = {"smoke": 6, "campaign": 60, "independent": 12}[profile]
    for i in range(count):
        name = f"sapi-{i:03d}.wav"
        path = root / name
        samples = np.array([int(1600 * np.sin(k / 5)) for k in range(16000)], dtype="<i2")
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(samples.tobytes())
        pos = i < count // 2
        cases.append({
            "file": name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "voice_id": "Windows SAPI installed test voice",
            "locale": "en-US",
            "rate": (0 if i % 2 == 0 else 2),
            "text": ("Hey Jarvis, what time is it?" if pos
                     else "Jarvis is a digital assistant."),
            "label": "synthetic_positive" if pos else "synthetic_negative",
            "source_kind": "windows_sapi_synthetic",
        })
    return {"schema": 1, "profile": profile, "samples": cases}


class SyntheticWakeStressTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.manifest = fixture(self.root)

    def test_manifest_is_balanced_and_model_ready(self):
        self.assertEqual(validate_manifest(self.manifest, self.root), [])
        self.assertEqual(len(VARIANTS), 4)
        self.assertEqual(frozen_threshold(), 0.4)

    def test_all_synthetic_not_human_even_if_phrase_sounds_correct(self):
        incorrect = copy.deepcopy(self.manifest)
        incorrect["samples"][0]["source_kind"] = "recorded_human"
        self.assertIn("invalid_source_kind", validate_manifest(incorrect, self.root))

    def test_wrong_phrase_labels_or_threshold_are_not_allowed(self):
        bad = copy.deepcopy(self.manifest)
        bad["samples"][3]["text"] = "Hey Jarvis, start recording."
        self.assertIn("negative_contains_wake", validate_manifest(bad, self.root))
        bad = copy.deepcopy(self.manifest)
        bad["samples"][0]["text"] = "Jarvis?"
        self.assertIn("positive_missing_wake", validate_manifest(bad, self.root))
        bad = copy.deepcopy(self.manifest)
        bad["profile"] = "campaign"
        self.assertIn("wrong_profile_count", validate_manifest(bad, self.root))

    def test_duplicate_paths_invalid_hashes_and_outside_paths_fail(self):
        bad = copy.deepcopy(self.manifest)
        bad["samples"][1]["file"] = bad["samples"][0]["file"]
        self.assertIn("duplicate_file", validate_manifest(bad, self.root))
        bad = copy.deepcopy(self.manifest)
        bad["samples"][0]["file"] = "../private.wav"
        self.assertIn("invalid_audio_filename", validate_manifest(bad, self.root))
        bad = copy.deepcopy(self.manifest)
        bad["samples"][0]["sha256"] = "0" * 64
        self.assertIn("file_hash_mismatch", validate_manifest(bad, self.root))

    def test_corrupted_or_silent_wav_rejected(self):
        bad = copy.deepcopy(self.manifest)
        p = self.root / bad["samples"][0]["file"]
        p.write_bytes(b"not a wav")
        bad["samples"][0]["sha256"] = hashlib.sha256(p.read_bytes()).hexdigest()
        self.assertIn("invalid_wav", validate_manifest(bad, self.root))

    def test_campaign_must_have_sixty_distinct_base_clips(self):
        manifest = fixture(self.root, profile="campaign")
        self.assertEqual(validate_manifest(manifest, self.root), [])
        self.assertEqual(60 * len(VARIANTS), 240)


    def test_unseen_texts_are_frozen_and_disjoint_from_previous_campaign(self):
        from synthetic_wake_stress import (
            UNSEEN_POSITIVES, UNSEEN_NEGATIVES, validate_manifest
        )
        self.assertEqual(len(UNSEEN_POSITIVES), 6)
        self.assertEqual(len(UNSEEN_NEGATIVES), 6)
        self.assertEqual(len(set(UNSEEN_POSITIVES + UNSEEN_NEGATIVES)), 12)
        standard = fixture(self.root, profile="independent")
        for i, row in enumerate(standard["samples"]):
            row["text"] = (UNSEEN_POSITIVES + UNSEEN_NEGATIVES)[i]
        self.assertEqual(validate_manifest(standard, self.root), [])
        reused = copy.deepcopy(standard)
        reused["samples"][0]["text"] = "Hey Jarvis, what time is it?"
        self.assertIn("unseen_phrase_changed", validate_manifest(reused, self.root))

    def test_noise_is_deterministic_and_not_a_new_voice(self):
        pcm = np.full(16000, 900, dtype=np.int16)
        x = perturb_pcm(pcm, "noise_10db", "clip-001")
        self.assertTrue(np.array_equal(x, perturb_pcm(pcm, "noise_10db", "clip-001")))
        self.assertFalse(np.array_equal(x, pcm))
        self.assertTrue(np.array_equal(perturb_pcm(pcm, "clean", "clip-001"), pcm))
        self.assertEqual(x.dtype, np.int16)

    def test_cannot_claim_full_certification_from_synthetic_samples(self):
        results = [
            {"label": "synthetic_positive", "score": 0.75, "verified": True,
             "voice_id": "sapi_a", "variant": "clean"},
            {"label": "synthetic_positive", "score": 0.15, "verified": False,
             "voice_id": "sapi_a", "variant": "noise_10db"},
            {"label": "synthetic_negative", "score": 0.65, "verified": False,
             "voice_id": "sapi_a", "variant": "clean"},
            {"label": "synthetic_negative", "score": 0.03, "verified": False,
             "voice_id": "sapi_a", "variant": "noise_10db"},
        ]
        m = synthetic_metrics(results, verifier_used=True)
        self.assertEqual(m["synthetic_positive_baseline_recall"], 0.5)
        self.assertEqual(m["synthetic_negative_baseline_false_activations"], 1)
        self.assertEqual(m["synthetic_negative_verified_false_activations"], 0)
        self.assertEqual(m["synthetic_positive_verified_recall"], 0.5)
        self.assertIsNone(m["human_positive_false_reject_rate"])

    def test_absent_verifier_requires_unknown_verified_metrics(self):
        rows = [
            {"label": "synthetic_positive", "score": 0.7, "verified": None,
             "voice_id": "sapi_a", "variant": "clean"},
            {"label": "synthetic_negative", "score": 0.1, "verified": None,
             "voice_id": "sapi_a", "variant": "clean"},
        ]
        report = summarize_experiment(rows, verifier_used=False)
        self.assertEqual(report["status"], "SYNTHETIC_ONLY_MEASURED")
        self.assertIsNone(report["metrics"]["synthetic_positive_verified_recall"])
        self.assertFalse(report["human_positive_certified"])
        self.assertFalse(report["commercial_model_rights_certified"])
        self.assertEqual(report["independent_human_positive_count"], 0)

    def test_optional_unprompted_comparison_cannot_claim_human_certification(self):
        rows = [
            {"label": "synthetic_positive", "score": 0.7, "verified": False,
             "verified_unprompted": True, "voice_id": "voice", "variant": "clean"},
            {"label": "synthetic_negative", "score": 0.7, "verified": True,
             "verified_unprompted": False, "voice_id": "voice", "variant": "clean"},
        ]
        metrics = compare_prompt_strategies(rows)
        self.assertEqual(metrics["production_verified_positive_recall"], 0.0)
        self.assertEqual(metrics["experimental_unprompted_positive_recall"], 1.0)
        self.assertEqual(metrics["production_verified_negative_false_activations"], 1)
        self.assertEqual(metrics["experimental_unprompted_negative_false_activations"], 0)
        self.assertEqual(metrics["human_positive_certified"], False)
        self.assertEqual(metrics["mode"], "DIAGNOSTIC_NOT_DEPLOYED")
        rows[0]["verified_unprompted"] = None
        with self.assertRaises(ValueError):
            compare_prompt_strategies(rows)

    def test_unknown_or_invalid_predictions_fail_closed(self):
        rows = [
            {"label": "synthetic_positive", "score": float("nan"),
             "verified": True, "voice_id": "voice", "variant": "clean"},
            {"label": "synthetic_negative", "score": 0.1,
             "verified": False, "voice_id": "voice", "variant": "clean"},
        ]
        with self.assertRaises(ValueError):
            synthetic_metrics(rows, verifier_used=True)
        rows[0]["score"] = 0.1
        with self.assertRaises(ValueError):
            synthetic_metrics(rows, verifier_used=True)  # verifier must not trigger without baseline


if __name__ == "__main__":
    unittest.main()
