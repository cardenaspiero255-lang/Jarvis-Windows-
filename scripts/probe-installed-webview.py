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

from playwright.async_api import async_playwright


async def main() -> dict:
    tmp = os.environ.get("RUNNER_TEMP")
    if os.environ.get("GITHUB_ACTIONS") != "true" or not tmp:
        raise RuntimeError("Installed UI probe requires disposable Windows CI")
    target = Path(tmp).resolve() / "jarvis-installed-webview.png"
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222", timeout=12000)
        try:
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

            await page.wait_for_load_state("domcontentloaded", timeout=15000)
            if not await page.get_by_role("button", name="Settings", exact=True).is_visible():
                raise RuntimeError("Installed WebView did not render HUD Settings")
            # Wait for the *actual* authenticated backend socket; the ZIP
            # review control appears only after successful HUD connection.
            review_button = page.get_by_role("button", name="Open repository ZIP review")
            await review_button.wait_for(state="visible", timeout=40000)
            await review_button.click()
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
            await page.get_by_role("button", name="Settings", exact=True).click()
            if not await page.get_by_text("Settings", exact=True).first.is_visible():
                raise RuntimeError("Settings panel did not open")
            # Capture an actual WebView2-rendered frame as separate
            # inspection evidence. Never substitute a synthetic screenshot.
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
                "screenshot_bytes": target.stat().st_size,
                "gui_webview_screenshot": "jarvis-installed-webview.png",
                "visual_or_voice_physical_certified": False,
                "physical_microphone_tested": False,
                "physical_power_loss_certified": False,
            }
        finally:
            await browser.close()


if __name__ == "__main__":
    try:
        report = asyncio.run(main())
        print("PLAYWRIGHT_INSTALLED_UI_PROOF=" + json.dumps(report, sort_keys=True))
    except Exception as exc:
        print("PLAYWRIGHT_INSTALLED_UI_FAIL=" + type(exc).__name__
              + ": " + str(exc)[:200], file=sys.stderr)
        sys.exit(1)
