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
        self.assertNotIn("hyperv-powercut-acceptance.ps1", workflow)
        self.assertNotIn("powercut_certified: true", workflow.lower())


if __name__ == "__main__":
    unittest.main()
