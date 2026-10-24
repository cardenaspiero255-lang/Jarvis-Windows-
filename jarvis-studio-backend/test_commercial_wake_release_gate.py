"""Red/green regressions: public releases cannot rely on unlicensed wake weights."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from commercial_wake_release_gate import check_commercial_wake_release


class CommercialWakeGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "jarvis-studio-backend/wake_word/openwakeword.py"
        self.model = self.root / "jarvis-studio-backend/wake_word/models/hey_jarvis.onnx"
        self.source.parent.mkdir(parents=True)
        self.model.parent.mkdir(parents=True)
        self.model.write_bytes(b"permissively-licensed-test-model" * 5000)
        self.sha = hashlib.sha256(self.model.read_bytes()).hexdigest()
        self.source.write_text("def _build_recognizer():\n    return CustomInference('model')\n", encoding="utf-8")

    def test_current_builtin_fallback_blocks_even_with_attestation_and_hash(self):
        self.source.write_text("def _build_recognizer():\n    return BuiltinInference(_BUILTIN_MODEL)\n")
        self.assertIn("noncommercial_builtin_wake_fallback", check_commercial_wake_release(
            self.root, rights_reviewed="true", expected_sha256=self.sha)["blockers"])

    def test_missing_rights_review_or_hash_blocks_publication(self):
        self.assertIn("commercial_rights_not_reviewed", check_commercial_wake_release(
            self.root, rights_reviewed="false", expected_sha256=self.sha)["blockers"])
        self.assertIn("approved_model_hash_missing", check_commercial_wake_release(
            self.root, rights_reviewed="true", expected_sha256="")["blockers"])

    def test_missing_or_tampered_weight_is_rejected(self):
        self.assertIn("approved_model_hash_mismatch", check_commercial_wake_release(
            self.root, rights_reviewed="true", expected_sha256="a" * 64)["blockers"])
        self.model.unlink()
        self.assertIn("approved_model_missing", check_commercial_wake_release(
            self.root, rights_reviewed="true", expected_sha256=self.sha)["blockers"])

    def test_only_custom_model_with_explicit_review_and_matching_digest_can_pass_technical_gate(self):
        report = check_commercial_wake_release(self.root, rights_reviewed="true", expected_sha256=self.sha)
        self.assertEqual(report["status"], "COMMERCIAL_WAKE_TECHNICAL_PRECHECK_PASS")
        self.assertFalse(report["legal_rights_certified"])
        self.assertFalse(report["installed_model_certified"])

    def test_no_symlink_model_or_missing_runtime_source(self):
        self.source.unlink()
        self.assertIn("wake_runtime_missing", check_commercial_wake_release(
            self.root, rights_reviewed="true", expected_sha256=self.sha)["blockers"])
        self.source.write_text("def _build_recognizer():\n    return CustomInference('model')\n")
        # Simulate a symlink without needing elevated Windows privileges.
        with patch.object(Path, "is_symlink", autospec=True, side_effect=lambda path: path == self.model):
            self.assertIn("approved_model_missing", check_commercial_wake_release(
                self.root, rights_reviewed="true", expected_sha256=self.sha)["blockers"])

    def test_release_workflow_must_check_before_publication(self):
        root = Path(__file__).resolve().parent.parent
        flow = (root / ".github/workflows/release.yml").read_text("utf-8")
        self.assertIn("commercial_wake_release_gate.py", flow)
        self.assertIn("WAKE_MODEL_APPROVED_SHA256", flow)
        self.assertIn("WAKE_MODEL_COMMERCIAL_RIGHTS_REVIEWED", flow)
        self.assertLess(flow.index("commercial_wake_release_gate.py"), flow.index("name: Publish the release"))


if __name__ == "__main__":
    unittest.main()
