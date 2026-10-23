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

    def test_uninstall_is_attempted_even_after_failed_ui_or_native_probe(self):
        script = (ROOT / "scripts" / "validate-installer.ps1").read_text(encoding="utf-8")
        self.assertIn("$installedRuntimeError", script)
        self.assertIn("Runtime probe failed; continuing to verify uninstallation", script)
        self.assertIn("Uninstall still required after runtime verification failure", script)
        self.assertLess(script.index("Runtime probe failed; continuing to verify uninstallation"),
                        script.index("$uninstallerExitCode = Invoke-BoundedProcess"))
        self.assertIn("$installedRuntimeVerified", script)
        self.assertIn("success = [bool]$success", script)

    def test_installer_receipt_reports_native_ws_independently_of_ui(self):
        source = (ROOT / "scripts" / "validate-installer.ps1").read_text(encoding="utf-8")
        self.assertIn('installed_runtime_ws_acceptance = [bool]($runtimeReceipt -and', source)
        self.assertIn('$runtimeReceipt.native_authenticated_websocket_verified', source)
        self.assertIn('installed_runtime_qwen_acceptance = [bool]($runtimeReceipt -and', source)
        self.assertIn('$runtimeReceipt.ollama_gguf_tested_in_installed_process', source)
        self.assertIn('application_functional_acceptance = [bool]$installedRuntimeVerified', source)

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

    def test_failure_of_real_webview_does_not_skip_native_backend_and_qwen(self):
        source = (ROOT / "scripts" / "probe-installed-runtime.ps1").read_text(encoding="utf-8")
        ui_start = source.index('probe-installed-webview.py')
        ws_start = source.index('probe-installed-websocket.py')
        final_gate = source.index('if (-not $pass)')
        self.assertLess(ui_start, ws_start)
        self.assertLess(ws_start, final_gate)
        # A failed UI diagnosis must not throw before attempting the native WS probe.
        self.assertNotIn('throw "Actual installed WebView2 UI interaction FAILED', source)
        self.assertIn('webview_probe_failed', source)
        self.assertIn('websocket_probe_failed', source)
        self.assertIn('jarvis-installed-ui-diagnostic.json', source)
        self.assertIn('webview_probe_failure_code', source)

    def test_cdp_listener_readiness_is_waited_for_before_playwright_attach(self):
        source = (ROOT / "scripts" / "probe-installed-webview.py").read_text(encoding="utf-8")
        self.assertIn("wait_for_cdp_ready", source)
        self.assertIn("/json/version", source)
        self.assertIn("cdp_listener_timeout", source)
        self.assertLess(source.index("await wait_for_cdp_ready"),
                        source.index("p.chromium.connect_over_cdp"))

    def test_installed_ui_failure_diagnostics_are_structured_and_nonsecret(self):
        source = (ROOT / "scripts" / "probe-installed-webview.py").read_text(encoding="utf-8")
        workflow = (ROOT / ".github/workflows/installer-validation.yml").read_text(encoding="utf-8")
        self.assertIn("PLAYWRIGHT_INSTALLED_UI_FAIL=", source)
        self.assertIn("cdp_http_diagnostics", source)
        self.assertIn("jarvis-installed-ui-diagnostic.json", source)
        self.assertIn("sys.stdout", source)
        self.assertIn("jarvis-installed-ui-diagnostic.json", workflow)
        self.assertIn("if: always()", workflow)

    def test_physical_powercut_is_not_inferred_from_runner(self):
        script = (ROOT / "scripts/probe-installed-runtime.ps1").read_text()
        self.assertIn("physical_power_loss_certified", script)
        self.assertIn("$false", script)


if __name__ == "__main__":
    unittest.main()
