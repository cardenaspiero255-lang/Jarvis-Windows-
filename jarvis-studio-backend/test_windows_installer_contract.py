"""Installer smoke / VM power-cut gate contracts: fail before shipping a fake PASS."""
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WindowsInstallerAndPowercutContractTests(unittest.TestCase):
    def test_installer_smoke_must_execute_real_install_uninstall_with_receipts(self):
        source = (ROOT / "scripts" / "validate-installer.ps1").read_text(encoding="utf-8")
        for required in ("Get-FileHash", "SHA256", "Start-Process",
                         "/S", "jarvis-studio-gui.exe", "jarvis-backend.exe",
                         "uninstall", "installer-smoke-proof.json",
                         "ExitCode", "Throw"):
            with self.subTest(required=required):
                self.assertIn(required.lower(), source.lower())
        self.assertNotIn("exit 0 # assume", source.lower())

    def test_expected_binary_is_actual_cargo_output_not_product_title(self):
        source = (ROOT / "scripts" / "validate-installer.ps1").read_text(encoding="utf-8")
        self.assertIn("jarvis-studio-gui.exe", source)
        self.assertIn("Get-ItemProperty", source)
        self.assertIn("InstallLocation", source)
        self.assertIn("installed_location", source)
        self.assertIn("installer-smoke-proof.json", source)

    def test_installer_receipt_never_claims_untested_gui_or_electrical_power_loss(self):
        source = (ROOT / "scripts" / "validate-installer.ps1").read_text(encoding="utf-8")
        self.assertIn("$false", source)
        self.assertIn("physical_power_loss_certified", source)
        self.assertIn("gui_launched", source)
        self.assertIn("uninstall_removed_gui", source)


    def test_real_ollama_server_and_installed_probe_share_one_runner_step(self):
        """GITHUB_ENV persists strings, not the Ollama server's process lifetime."""
        workflow = (ROOT / ".github/workflows/installer-validation.yml").read_text(encoding="utf-8")
        bootstrap = (ROOT / "scripts/prepare-installed-ollama.ps1").read_text(encoding="utf-8")
        self.assertIn("prepare-installed-ollama.ps1 -InstallerPath", workflow)
        self.assertNotIn("run: ./scripts/prepare-installed-ollama.ps1\\n", workflow)
        self.assertIn("validate-installer.ps1", bootstrap)
        self.assertIn("finally", bootstrap)
        self.assertIn("Stop-Process", bootstrap)
        self.assertIn("OLLAMA_HOST", bootstrap)
        self.assertIn("api/tags", bootstrap)
        self.assertIn("JARVIS_INSTALLED_REAL_OLLAMA", bootstrap)

    def test_ci_proves_unsigned_publication_gate_refuses_installer(self):
        workflow = (ROOT / ".github" / "workflows" /
                    "installer-validation.yml").read_text("utf-8")
        self.assertIn("verify-release-signature.ps1", workflow)
        self.assertIn("jarvis-release-signature-proof.json", workflow)
        self.assertIn("expected denial", workflow.lower())

    def test_resolved_python_release_dependency_bill_is_attached(self):
        workflow = (ROOT / ".github" / "workflows" /
                    "installer-validation.yml").read_text("utf-8")
        packager = (ROOT / "scripts" / "package-backend.ps1").read_text("utf-8")
        self.assertIn("pip list --format=json", packager)
        self.assertIn("jarvis-python-build-dependencies.txt", packager)
        self.assertIn("jarvis-python-build-dependencies.txt", workflow)

    def test_pr_build_must_never_publish_release(self):
        workflow = (ROOT / ".github" / "workflows" / "installer-validation.yml").read_text(encoding="utf-8")
        self.assertIn("pull_request:", workflow)
        self.assertIn("windows-latest", workflow)
        self.assertIn("scripts/build.ps1 -Lean", workflow)
        self.assertIn("scripts/validate-installer.ps1", workflow)
        self.assertIn("actions/upload-artifact", workflow)
        self.assertNotIn("action-gh-release", workflow)
        self.assertNotIn("contents: write", workflow)

    def test_installer_build_requires_backend_and_nsis(self):
        source = (ROOT / "scripts" / "build.ps1").read_text(encoding="utf-8")
        self.assertIn("param(", source)
        self.assertIn("[switch]$Lean", source)
        self.assertIn("-Lean", source)
        self.assertIn("jarvis-backend.exe", source)
        self.assertIn("installer", source.lower())

    def test_vm_powercut_can_only_target_explicit_disposable_guest(self):
        source = (ROOT / "scripts" / "hyperv-powercut-acceptance.ps1").read_text(encoding="utf-8")
        for token in ("Stop-VM", "-TurnOff", "Start-VM", "New-PSSession",
                      "JARVIS-DISPOSABLE-", "IUnderstandVirtualPowerCut",
                      "vm-powercut-proof.json"):
            self.assertIn(token, source)
        self.assertNotIn("Stop-Computer", source)
        self.assertNotIn("Restart-Computer", source)

    def test_powercut_lab_is_not_marked_certified_in_ordinary_pr_ci(self):
        workflow = (ROOT / ".github" / "workflows" / "installer-validation.yml").read_text(encoding="utf-8")
        self.assertNotIn("run: ./scripts/hyperv-powercut-acceptance.ps1", workflow)
        self.assertNotIn("Stop-VM -TurnOff", workflow)
        self.assertNotIn("powercut_certified: true", workflow.lower())


    def test_failed_real_webview_click_preserves_obstruction_evidence(self):
        source = (ROOT / "scripts" / "probe-installed-webview.py").read_text("utf-8")
        workflow = (ROOT / ".github" / "workflows" /
                    "installer-validation.yml").read_text("utf-8")
        self.assertIn("document.elementFromPoint", source)
        self.assertIn("jarvis-installed-webview-failure.png", source)
        self.assertIn("screenshot_on_failure", source)
        self.assertIn("jarvis-installed-webview-failure.png", workflow)
        self.assertIn("if: always()", workflow)

    def test_temporary_webview_policy_cleanup_is_verified_not_assumed(self):
        source = (ROOT / "scripts" / "probe-installed-runtime.ps1").read_text("utf-8")
        self.assertIn("cdp_policy_cleanup_error_type", source)
        self.assertIn("cdp_policy_value_absent_verified", source)
        self.assertIn("Get-ItemProperty", source)

    def test_installed_webview_waits_for_real_backend_setup_ack_before_interactions(self):
        probe = (ROOT / "scripts" / "probe-installed-webview.py").read_text("utf-8")
        app = (ROOT / "jarvis-studio-gui" / "src" / "App.jsx").read_text("utf-8")
        self.assertIn('data-jarvis-backend-setup-state', app)
        self.assertIn('wait_for_backend_setup_state', probe)
        self.assertIn('wait_for(state="visible"', probe)
        self.assertIn('backend_setup_acknowledged', probe)
        self.assertLess(probe.index('backend_setup_acknowledged'),
                        probe.index('await review_button.click'))
        self.assertIn('state="attached"', probe)



    def test_full_installer_can_be_downloaded_privately_with_matching_sha(self):
        """Physical notebook tests need the exact CI-tested FULL exe, not receipts."""
        workflow = (ROOT / ".github/workflows/windows-full-whisper-acceptance.yml").read_text("utf-8")
        self.assertIn("jarvis-unsigned-full-notebook-test", workflow)
        self.assertIn("if: success()", workflow)
        self.assertIn("Get-FileHash", workflow)
        self.assertIn("SHA256", workflow)
        self.assertIn("jarvis-full-installer.sha256", workflow)
        self.assertIn("jarvis-studio-gui/src-tauri/target/release/bundle/nsis/*.exe", workflow)
        self.assertIn("retention-days: 7", workflow)
        self.assertNotIn("action-gh-release", workflow)
        self.assertNotIn("contents: write", workflow)

if __name__ == "__main__":
    unittest.main()
