"""Real installed JARVIS WebView2 accessibility/interaction acceptance using CDP.

No simulated page, mocked DOM, or development Vite server. CDP is enabled
ONLY on the ephemeral Windows acceptance runner; never in a release build.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
import urllib.request
import urllib.parse

# Never log a page URL, query string, bearer token, profile path, or JS state.
_PHASE = "bootstrap"
_CLICK_DIAGNOSTICS = {}


def cdp_http_diagnostics() -> dict:
    """Bounded, read-only localhost CDP readiness with nonsecret metadata."""
    status = {"cdp_version_http": False, "cdp_target_count": -1,
              "version_error_type": "none", "targets_error_type": "none"}
    for endpoint, label in (("/json/version", "version"), ("/json/list", "targets")):
        try:
            with urllib.request.urlopen("http://127.0.0.1:9222" + endpoint, timeout=3) as response:
                payload = json.load(response)
            if label == "version":
                status["cdp_version_http"] = True
                status["browser_kind"] = "WebView2" if "WebView" in str(payload.get("Browser", "")) else "other"
            else:
                status["cdp_target_count"] = len(payload) if isinstance(payload, list) else -1
                origins = set()
                if isinstance(payload, list):
                    for item in payload[:20]:
                        if isinstance(item, dict):
                            parsed = urllib.parse.urlsplit(str(item.get("url", "")))
                            if parsed.scheme in ("http", "https", "tauri"):
                                origins.add(parsed.scheme + "://" + parsed.netloc)
                status["cdp_target_origins"] = sorted(origins)
        except (OSError, ValueError, TypeError) as exc:
            status[label + "_error_type"] = type(exc).__name__
    return status


def _phase(value: str) -> None:
    global _PHASE
    _PHASE = value

from playwright.async_api import async_playwright


async def wait_for_cdp_ready(seconds: int = 90) -> None:
    """Do not attach before WebView2 finishes asynchronously creating CDP."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + seconds
    while loop.time() < deadline:
        try:
            with urllib.request.urlopen("http://127.0.0.1:9222/json/version",
                                        timeout=3) as response:
                info = json.load(response)
            # A listening but unrelated process must not be accepted.
            if isinstance(info, dict) and info.get("webSocketDebuggerUrl"):
                return
        except (OSError, ValueError, TypeError):
            pass
        await asyncio.sleep(2)
    raise RuntimeError("cdp_listener_timeout")


async def main() -> dict:
    tmp = os.environ.get("RUNNER_TEMP")
    if os.environ.get("GITHUB_ACTIONS") != "true" or not tmp:
        raise RuntimeError("Installed UI probe requires disposable Windows CI")
    target = Path(tmp).resolve() / "jarvis-installed-webview.png"
    _phase("wait_for_cdp")
    await wait_for_cdp_ready()
    _phase("connect_cdp")
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222", timeout=12000)
        try:
            _phase("discover_packaged_window")
            page = None
            loop = asyncio.get_running_loop()
            deadline = loop.time() + 90
            while loop.time() < deadline:
                for context in browser.contexts:
                    for candidate in context.pages:
                        if (candidate.url.startswith(("http://tauri.localhost",
                                                       "https://tauri.localhost",
                                                       "tauri://localhost"))
                                and await candidate.get_by_role("button", name="Settings",
                                                                exact=True).count()):
                            page = candidate
                            break
                    if page:
                        break
                if page:
                    break
                await asyncio.sleep(2)
            if page is None:
                raise RuntimeError("Real packaged WebView2 main HUD was not discoverable")

            _phase("render_settings")
            await page.wait_for_load_state("domcontentloaded", timeout=15000)
            if not await page.get_by_role("button", name="Settings", exact=True).is_visible():
                raise RuntimeError("Installed WebView did not render HUD Settings")
            # A disposable fresh installation legitimately opens the first-run
            # onboarding dialog ABOVE the normal HUD (and Review ZIP). Playwright
            # may find Review ZIP "visible" but cannot click through that modal.
            # Complete the REAL supported local-only setup rather than using
            # force clicks, injecting React state, or inventing cloud API keys.
            _phase("wait_for_backend_setup_state")
            # WebSocket connection can precede the first authenticated sysinfo.
            # An absent onboarding dialog is NOT proof that setup is complete.
            setup_state = page.locator("[data-jarvis-backend-setup-state]")
            await page.wait_for_function("""() => {
                const state = document.querySelector(
                    "[data-jarvis-backend-setup-state]"
                )?.getAttribute("data-jarvis-backend-setup-state");
                return state === "required" || state === "complete";
            }""", timeout=60000)
            state = await setup_state.get_attribute("data-jarvis-backend-setup-state")
            onboarding = page.get_by_role("dialog", name="Welcome to JARVIS")
            if state == "required":
                _phase("complete_local_onboarding")
                await onboarding.wait_for(state="visible", timeout=15000)
                await onboarding.get_by_role(
                    "checkbox", name="Use local Ollama (no API key)"
                ).check(timeout=12000)
                await onboarding.locator('input[type="text"]').fill(
                    str(Path(tmp).resolve() / "JARVIS-E2E-LOCAL-FILES"), timeout=12000
                )
                await onboarding.get_by_role("button", name="Start JARVIS").click(
                    timeout=12000
                )
            elif state != "complete":
                raise RuntimeError("backend_setup_state_invalid")
            # Saving config yields a fresh backend 'config'/'sysinfo' event
            # with needs_setup=False. This is an acknowledgement, not merely
            # a local click or a hidden modal.
            _phase("verify_backend_setup_ack")
            backend_setup_acknowledged = page.locator(
                '[data-jarvis-backend-setup-state="complete"]'
            )
            await backend_setup_acknowledged.wait_for(state="attached", timeout=40000)
            await onboarding.wait_for(state="hidden", timeout=20000)
            # A real first-run download/repair overlay may still be active. It
            # must genuinely finish instead of being hidden by the test.
            _phase("wait_for_packaged_setup")
            progress = page.locator(".setup-overlay")
            await progress.wait_for(state="hidden", timeout=90000)
            # Wait for the *actual* authenticated backend socket; the ZIP
            # review control appears only after successful HUD connection.
            _phase("connect_authenticated_hud")
            review_button = page.get_by_role("button", name="Open repository ZIP review")
            await review_button.wait_for(state="visible", timeout=40000)
            # A visible microphone control proves only UI affordance, not actual
            # capture hardware, owner voice or offline ASR.
            if not await page.get_by_role("button", name="Talk", exact=True).is_visible():
                raise RuntimeError("Installed HUD microphone control is missing")
            _phase("exercise_repository_dialog")
            try:
                await review_button.click(timeout=15000)
            except Exception:
                # A genuine input failure must be diagnosed, never forced.
                # Report only element classes, never page text, URL, bearer or DOM.
                try:
                    _CLICK_DIAGNOSTICS.update(await review_button.evaluate("""(el) => {
                        const rect = el.getBoundingClientRect();
                        const x = rect.left + rect.width / 2;
                        const y = rect.top + rect.height / 2;
                        const hit = document.elementFromPoint(x, y);
                        const css = hit ? getComputedStyle(hit) : null;
                        return {
                            target_has_box: rect.width > 0 && rect.height > 0,
                            click_target_obscured: !!hit && hit !== el && !el.contains(hit),
                            hit_element_tag: hit?.tagName?.toLowerCase() || "none",
                            hit_element_role: hit?.getAttribute("role") || "none",
                            hit_element_pointer_events: css?.pointerEvents || "unknown"
                        };
                    }"""))
                except Exception as diagnostic_exc:
                    _CLICK_DIAGNOSTICS["hit_test_error_type"] = type(diagnostic_exc).__name__
                raise
            _phase("verify_repository_dialog_visible")
            dialog = page.get_by_role("dialog", name="Repository review")
            await dialog.wait_for(state="visible", timeout=10000)
            if not await dialog.locator('input[type="file"][accept*=".zip"]').count():
                raise RuntimeError("Installed ZIP review did not expose file-picker UI")
            if await dialog.get_by_role("button", name="Approve modified copy").count():
                raise RuntimeError("Unreviewed ZIP exposed approval button")
            await dialog.get_by_role("button", name="Close").click()
            await dialog.wait_for(state="hidden", timeout=10000)

            # The settings pane must also open through a real user-facing
            # click. We do not enable permissions or microphone in CI.
            _phase("open_settings_panel")
            await page.get_by_role("button", name="Settings", exact=True).click()
            settings_dialog = page.get_by_role("dialog", name="Settings")
            await settings_dialog.wait_for(state="visible", timeout=10000)
            if not await settings_dialog.get_by_role("button", name="Close settings").is_visible():
                raise RuntimeError("Settings panel did not expose its close control")
            # Capture an actual WebView2-rendered frame as separate
            # inspection evidence. Never substitute a synthetic screenshot.
            _phase("capture_real_webview")
            await page.screenshot(path=str(target), animations="disabled")
            if target.stat().st_size < 4000:
                raise RuntimeError("Installed WebView screenshot missing/empty")
            return {
                "status": "real_installed_webview2_ui_verified",
                "cdp_real_packaged_tauri_webview2": True,
                "hud_settings_rendered": True,
                "repo_zip_dialog_opened_and_closed": True,
                "unapproved_patch_cannot_be_approved_in_ui": True,
                "settings_opened_by_real_click": True,
                "voice_talk_control_rendered": True,
                "screenshot_bytes": target.stat().st_size,
                "gui_webview_screenshot": "jarvis-installed-webview.png",
                "visual_or_voice_physical_certified": False,
                "physical_microphone_tested": False,
                "physical_power_loss_certified": False,
            }
        except Exception:
            # Preserve a REAL screenshot of the failure before detaching CDP.
            # This artifact is diagnostic; it never counts as UI acceptance.
            if page is not None and not page.is_closed():
                try:
                    failed_frame = Path(tmp).resolve() / "jarvis-installed-webview-failure.png"
                    await page.screenshot(path=str(failed_frame),
                                          animations="disabled", timeout=5000)
                    _CLICK_DIAGNOSTICS["screenshot_on_failure"] = (
                        failed_frame.is_file() and failed_frame.stat().st_size > 0
                    )
                except Exception as screenshot_exc:
                    _CLICK_DIAGNOSTICS["screenshot_on_failure"] = False
                    _CLICK_DIAGNOSTICS["screenshot_error_type"] = type(screenshot_exc).__name__
            raise
        finally:
            await browser.close()


if __name__ == "__main__":
    try:
        report = asyncio.run(main())
        print("PLAYWRIGHT_INSTALLED_UI_PROOF=" + json.dumps(report, sort_keys=True))
    except Exception as exc:
        # The real failure is evidence; never bypass the UI gate.
        # A concise stdout JSON survives pwsh's native stderr handling.
        report = {
            "status": "real_installed_ui_failed",
            "stage": _PHASE,
            "error_type": type(exc).__name__,
            "cdp_http_diagnostics": cdp_http_diagnostics(),
            "click_diagnostics": _CLICK_DIAGNOSTICS,
            "screenshot_on_failure": bool(_CLICK_DIAGNOSTICS.get("screenshot_on_failure", False)),
            "screenshot_present": (Path(os.environ.get("RUNNER_TEMP", ".")) /
                                   "jarvis-installed-webview.png").is_file(),
            "physical_power_loss_certified": False,
            "success": False,
        }
        directory = os.environ.get("RUNNER_TEMP")
        if directory:
            try:
                (Path(directory) / "jarvis-installed-ui-diagnostic.json").write_text(
                    json.dumps(report, sort_keys=True), encoding="utf-8")
            except OSError:
                pass
        print("PLAYWRIGHT_INSTALLED_UI_FAIL=" + json.dumps(report, sort_keys=True),
              file=sys.stdout, flush=True)
        sys.exit(1)
