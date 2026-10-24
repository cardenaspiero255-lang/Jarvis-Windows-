"""RED: FULL offline clean-licence bundle must be audited before NSIS release."""
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from full_offline_bundle_audit import audit_full_bundle


class FullBundleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "jarvis-backend.exe").write_bytes(b"MZ" + b"x" * 120000)
        self.preload = self.root / "preload-assets"
        (self.preload / "whisper-base").mkdir(parents=True)
        (self.preload / "piper").mkdir(parents=True)
        (self.preload / "ms-playwright" / "chromium-999" / "chrome-win").mkdir(parents=True)
        (self.preload / "whisper-base" / "model.bin").write_bytes(b"w" * 120000)
        (self.preload / "whisper-base" / "config.json").write_text('{"model_type":"whisper"}')
        (self.preload / "piper" / "en_US-john-medium.onnx").write_bytes(b"p" * 120000)
        (self.preload / "piper" / "en_US-john-medium.onnx.json").write_text("{}")
        (self.preload / "ms-playwright" / "chromium-999" / "chrome-win" / "chrome.exe").write_bytes(b"MZ" + b"c" * 120000)

    def test_valid_full_bundle_has_required_assets_but_not_certification(self):
        receipt = audit_full_bundle(self.root, engine="whisper_local")
        self.assertEqual(receipt["status"], "FULL_ASSETS_PRESENT_NOT_CERTIFIED")
        self.assertEqual(receipt["blockers"], [])
        self.assertFalse(receipt["installed_full_runtime_certified"])
        self.assertFalse(receipt["license_rights_certified"])
        self.assertEqual(len(receipt["hashes"]), 4)

    def test_restricted_oww_pretrained_model_blocks_even_with_full_whisper(self):
        p = self.root / "_internal" / "openwakeword" / "resources" / "models"
        p.mkdir(parents=True)
        (p / "hey_jarvis_v0.1.onnx").write_bytes(b"a" * 1000)
        report = audit_full_bundle(self.root, engine="whisper_local")
        self.assertIn("restricted_openwakeword_assets_present", report["blockers"])

    def test_missing_piper_voice_config_or_whisper_weights_fail(self):
        (self.preload / "piper" / "en_GB-alan-medium.onnx.json").unlink()
        self.assertIn("piper_voice_config_missing", audit_full_bundle(
            self.root, engine="whisper_local")["blockers"])
        (self.preload / "whisper-base" / "model.bin").unlink()
        self.assertIn("whisper_model_missing", audit_full_bundle(
            self.root, engine="whisper_local")["blockers"])

    def test_rejects_dev_oww_engine_and_lean_assets(self):
        self.assertIn("not_licensed_wake_engine", audit_full_bundle(
            self.root, engine="openwakeword_development")["blockers"])
        (self.preload / "ms-playwright" / "chromium-999" / "chrome-win" / "chrome.exe").unlink()
        self.assertIn("chromium_missing", audit_full_bundle(
            self.root, engine="whisper_local")["blockers"])

    def test_no_symlink_in_required_assets(self):
        with patch.object(Path, "is_symlink", autospec=True,
                                        side_effect=lambda p: p.name == "model.bin"):
            self.assertIn("whisper_model_missing", audit_full_bundle(
                self.root, engine="whisper_local")["blockers"])


    def test_old_alan_weights_from_preload_cache_block_commercial_bundle(self):
        stale = self.preload / "piper" / "en_GB-alan-medium.onnx"
        stale.write_bytes(b"old" * 1000)
        self.assertIn("unreviewed_alan_voice_present", audit_full_bundle(
            self.root, engine="whisper_local")["blockers"])

    def test_piper_defaults_use_public_domain_training_source(self):
        root = Path(__file__).resolve().parent.parent
        for path in (
            "jarvis-studio-backend/tts/tts_engine.py",
            "scripts/prefetch_preload_assets.py",
            "jarvis-studio-backend/real_neural_voice_e2e.py",
        ):
            with self.subTest(path=path):
                source = (root / path).read_text("utf-8")
                self.assertIn('en_US-john-medium', source)
                self.assertNotIn('= "en_GB-alan-medium"', source)


    def test_preload_cache_copy_must_allowlist_assets_not_wildcard_all_files(self):
        root = Path(__file__).resolve().parent.parent
        ps1 = (root / "scripts" / "package-backend.ps1").read_text("utf-8")
        self.assertNotIn('Copy-Item -Path (Join-Path $Cache "*")', ps1)
        self.assertIn('("ms-playwright", "whisper-base", "piper")', ps1)
        self.assertIn('LinkType', ps1)

    def test_build_requires_clean_whisper_mode_and_frozen_runtime_hook(self):
        root = Path(__file__).resolve().parent.parent
        spec = (root / "jarvis-studio-backend" / "jarvis-backend.spec").read_text("utf-8")
        package = (root / "scripts" / "package-backend.ps1").read_text("utf-8")
        hook = (root / "jarvis-studio-backend" / "wake_word" / "frozen_engine_runtime.py").read_text("utf-8")
        self.assertIn("JARVIS_WAKE_PACKAGE_MODE", spec)
        self.assertIn("runtime_hooks=", spec)
        self.assertIn("JARVIS_WAKE_PACKAGE_MODE", package)
        self.assertIn('os.environ["JARVIS_WAKE_ENGINE"] = "whisper_local"', hook)


if __name__ == "__main__":
    unittest.main()
