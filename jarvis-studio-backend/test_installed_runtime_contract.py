"""Fail-closed contracts for actually launching installed GUI+frozen backend."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class InstalledRuntimeContractTests(unittest.TestCase):
    def test_installer_workflow_runs_real_packaged_process_probe(self):
        workflow = (ROOT / ".github/workflows/installer-validation.yml").read_text()
        self.assertIn("probe-installed-runtime.ps1", workflow)
        self.assertIn("probe-installed-websocket.py", workflow)
        self.assertIn("jarvis-installed-runtime-proof.json", workflow)
        self.assertIn("websockets==12.0", workflow)

    def test_installer_can_only_uninstall_after_runtime_probe(self):
        script = (ROOT / "scripts/validate-installer.ps1").read_text()
        self.assertIn("probe-installed-runtime.ps1", script)
        self.assertIn("installed_runtime_verified", script)
        self.assertLess(script.index("probe-installed-runtime.ps1"),
                        script.index("$uninstallerExitCode = Invoke-BoundedProcess"))
        self.assertNotIn("gui_launched = $false", script)

    def test_packaged_gui_process_and_backend_are_separately_verified(self):
        script = (ROOT / "scripts/probe-installed-runtime.ps1").read_text()
        for value in ("jarvis-studio-gui.exe", "Get-CimInstance",
                      "jarvis-backend.exe", "Start-Process", "Stop-Process",
                      "JARVIS_WS_TOKEN", "RandomNumberGenerator",
                      "probe-installed-websocket.py", "RUNNER_TEMP"):
            self.assertIn(value, script)
        self.assertNotIn("JARVIS_SKIP_BACKEND_SPAWN", script)
        self.assertIn("not_certified", script)

    def test_websocket_test_requires_real_sender_events_and_denied_unauthorized(self):
        script = (ROOT / "scripts/probe-installed-websocket.py").read_text()
        for value in ("websockets.connect", "sysinfo", "repo_review.request",
                      "denied", "ConnectionClosed", "sha256", "status",
                      "JARVIS_WS_TOKEN"):
            self.assertIn(value, script)
        self.assertNotIn("mock", script)
        self.assertNotIn("localhost:1420", script)

    def test_webview2_installed_ui_requires_real_cdp_render_and_interaction(self):
        workflow = (ROOT / ".github/workflows" / "installer-validation.yml").read_text()
        probe = (ROOT / "scripts" / "probe-installed-runtime.ps1").read_text()
        browser = (ROOT / "scripts" / "probe-installed-webview.py").read_text()
        self.assertIn("playwright==", workflow)
        self.assertIn("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", probe)
        self.assertIn("probe-installed-webview.py", probe)
        self.assertIn("installed_webview_ui_verified", probe)
        for token in ("connect_over_cdp", "get_by_role", "Open repository ZIP review",
                      "Repository review", "Settings", "screenshot"):
            self.assertIn(token, browser)
        self.assertIn("visual_or_voice_physical_certified", browser)
        self.assertNotIn("virtual microphone device passed", browser)

    def test_physical_powercut_is_not_inferred_from_runner(self):
        script = (ROOT / "scripts/probe-installed-runtime.ps1").read_text()
        self.assertIn("physical_power_loss_certified", script)
        self.assertIn("$false", script)


if __name__ == "__main__":
    unittest.main()
