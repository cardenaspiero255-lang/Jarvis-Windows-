"""Evidence verifier rejects mock catalogs without real GGUF metadata."""
import unittest
from real_local_model_e2e import get_model_evidence

class RealLocalModelEvidenceTests(unittest.TestCase):
    def test_requires_gguf_and_digest(self):
        model = "qwen2.5-coder:0.5b"
        sha = "d" * 64
        mock = lambda _: {"models": [{
            "name": model,
            "digest": sha,
            "details": {"format": "gguf", "family": "qwen2"},
        }]}
        report = get_model_evidence("http://127.0.0.1:11434", model, fetch=mock)
        self.assertEqual(report["model_digest"], sha)
        self.assertEqual(report["model_format"], "gguf")

    def test_refuses_missing_model_or_fake_non_gguf(self):
        for models in (
            [],
            [{"name": "other", "digest": "b" * 64, "details": {"format": "gguf"}}],
            [{"name": "qwen2.5-coder:0.5b", "digest": "oops", "details": {"format": "gguf"}}],
            [{"name": "qwen2.5-coder:0.5b", "digest": "b" * 64, "details": {"format": "cloud"}}],
        ):
            with self.subTest(models=models), self.assertRaises(RuntimeError):
                get_model_evidence(fetch=lambda _: {"models": models})
