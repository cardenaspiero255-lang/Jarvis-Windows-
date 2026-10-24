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
        self.spec = self.root / "jarvis-studio-backend/jarvis-backend.spec"
        self.package = self.root / "scripts/package-backend.ps1"
        self.package.parent.mkdir(parents=True, exist_ok=True)
        self.spec.write_text("datas = []\n", encoding="utf-8")
        self.package.write_text("# approved custom model packager\n", encoding="utf-8")
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


    def test_pretrained_model_packaging_is_blocked_even_if_runtime_custom_model_is_approved(self):
        self.spec.write_text('datas += collect_data_files("openwakeword")\n')
        out = check_commercial_wake_release(
            self.root, rights_reviewed="true", expected_sha256=self.sha)
        self.assertIn("noncommercial_openwakeword_data_packaged", out["blockers"])

        self.spec.write_text("datas = []\n")
        self.package.write_text('& $python -c "import openwakeword.utils as u; u.download_models()"\n')
        out = check_commercial_wake_release(
            self.root, rights_reviewed="true", expected_sha256=self.sha)
        self.assertIn("pretrained_openwakeword_weights_downloaded", out["blockers"])

    def test_packaging_source_files_mandatory_to_prevent_fake_precheck_pass(self):
        self.spec.unlink()
        self.assertIn("pyinstaller_spec_missing", check_commercial_wake_release(
            self.root, rights_reviewed="true", expected_sha256=self.sha)["blockers"])
        self.spec.write_text("datas = []\n")
        self.package.unlink()
        self.assertIn("backend_packager_missing", check_commercial_wake_release(
            self.root, rights_reviewed="true", expected_sha256=self.sha)["blockers"])


    def test_clean_whisper_source_route_requires_exact_packaged_runtime_and_owner_review(self):
        from commercial_wake_release_gate import check_commercial_wake_release
        hook = self.root / "jarvis-studio-backend/wake_word/frozen_engine_runtime.py"
        hook.write_text('os.environ["JARVIS_WAKE_ENGINE"] = "whisper_local"')
        self.source.write_text(
            'if engine == "whisper_local": return LocalWhisperWake()\n'
            'return BuiltinInference("dev only")\n')
        self.spec.write_text(
            'clean_wake_bundle = os.environ.get("JARVIS_WAKE_PACKAGE_MODE") == "whisper_local"\n'
            'runtime_hooks=[str(root / "wake_word" / "frozen_engine_runtime.py")] if clean_wake_bundle else [],\n'
            'if not clean_wake_bundle:\n    datas += collect_data_files("openwakeword")\n'
            'excludes.append("openwakeword")\n')
        self.package.write_text(
            'if ($env:JARVIS_WAKE_PACKAGE_MODE -eq "whisper_local") {\n'
            '    Write-Output "No openwakeword download"\n'
            '} else { download_models() }\n')
        self.assertEqual(check_commercial_wake_release(
            self.root, rights_reviewed="true", expected_sha256="",
            package_engine="whisper_local")["status"],
            "COMMERCIAL_WAKE_TECHNICAL_PRECHECK_PASS")
        self.assertIn("commercial_rights_not_reviewed", check_commercial_wake_release(
            self.root, rights_reviewed="false", expected_sha256="",
            package_engine="whisper_local")["blockers"])
        hook.unlink()
        self.assertIn("frozen_whisper_hook_missing", check_commercial_wake_release(
            self.root, rights_reviewed="true", expected_sha256="",
            package_engine="whisper_local")["blockers"])

    def test_release_workflow_must_check_before_publication(self):
        root = Path(__file__).resolve().parent.parent
        flow = (root / ".github/workflows/release.yml").read_text("utf-8")
        self.assertIn("commercial_wake_release_gate.py", flow)
        self.assertIn("WAKE_MODEL_APPROVED_SHA256", flow)
        self.assertIn("WAKE_MODEL_COMMERCIAL_RIGHTS_REVIEWED", flow)
        self.assertLess(flow.index("commercial_wake_release_gate.py"), flow.index("name: Publish the release"))


if __name__ == "__main__":
    unittest.main()
