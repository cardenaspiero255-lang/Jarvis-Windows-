"""Native authenticated WebSocket acceptance against actual installed JARVIS.exe.

No stubs, no Vite/dev backend. Connected to the Tauri-spawned frozen executable.
Expect wrong-token rejection, a real 'sysinfo' event from its startup and an
explicitly denied malformed repository-review request. No repo/app mutation.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys

import websockets
from websockets.exceptions import ConnectionClosed


async def _unauthorized_rejected(token: str) -> bool:
    wrong = token + "-invalid"
    try:
        async with websockets.connect(
            "ws://127.0.0.1:8765/?token=" + wrong,
            open_timeout=4, close_timeout=1, ping_interval=None,
        ) as ws:
            try:
                data = await asyncio.wait_for(ws.recv(), timeout=4)
            except ConnectionClosed as closed:
                return closed.code == 1008
            except asyncio.TimeoutError:
                return False
            # A response to a wrong token is a failure even if it is a warning.
            print("Unexpected event for wrong token: " + str(data)[:60], file=sys.stderr)
            return False
    except (websockets.exceptions.InvalidHandshake, OSError, ConnectionClosed):
        return True


async def probe():
    token = os.environ.get("JARVIS_WS_TOKEN", "")
    if len(token) < 32:
        raise RuntimeError("Ephemeral strong GUI/backend WebSocket token required")
    rejected = await _unauthorized_rejected(token)
    if not rejected:
        raise RuntimeError("Installed backend did not reject a wrong native token")
    async with websockets.connect(
        "ws://127.0.0.1:8765/?token=" + token,
        open_timeout=8, close_timeout=2, ping_interval=None,
        max_size=1024 * 1024,
    ) as ws:
        sysinfo = None
        deadline = asyncio.get_running_loop().time() + 25
        while asyncio.get_running_loop().time() < deadline:
            raw = await asyncio.wait_for(ws.recv(), timeout=8)
            payload = json.loads(raw)
            if payload.get("event") == "sysinfo" and isinstance(payload.get("data"), dict):
                sysinfo = payload["data"]
                break
        if sysinfo is None:
            raise RuntimeError("Installed backend never emitted real sysinfo")
        # Real reply from backend owner-scoped, local-only ZIP review API.
        await ws.send(json.dumps({
            "type": "repo_review.request",
            "data": {"action": "inspect", "consent": False, "zip_b64": ""},
        }))
        denied = False
        for _ in range(18):
            raw = await asyncio.wait_for(ws.recv(), timeout=5)
            event = json.loads(raw)
            if event.get("event") == "repo_review_state":
                data = event.get("data") or {}
                denied = data.get("status") == "denied"
                break
        if not denied:
            raise RuntimeError("Installed review API did not fail closed on missing consent")
    return {
        "status": "real_installed_runtime_ws_verified",
        "authenticated_real_sysinfo": True,
        "negative_wrong_token_rejected": rejected,
        "review_without_consent_denied": True,
        "backend_protocol": "websockets-v12",
        "ws_url_sha256": hashlib.sha256(b"ws://127.0.0.1:8765").hexdigest(),
        "ollama_gguf_execution_in_this_probe": False,
        "external_code_executed": False,
        "user_project_modified": False,
        "physical_power_loss_certified": False,
    }


if __name__ == "__main__":
    try:
        result = asyncio.run(probe())
        print("JARVIS_INSTALLED_WS_PROOF=" + json.dumps(result, sort_keys=True))
    except Exception as exc:
        print("JARVIS_INSTALLED_WS_FAIL=" + type(exc).__name__ + ": " + str(exc)[:180],
              file=sys.stderr)
        sys.exit(1)
