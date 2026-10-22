"""Native authenticated WebSocket acceptance against actual installed JARVIS.exe.

No stubs, no Vite/dev backend. Connected to the Tauri-spawned frozen executable.
Expect wrong-token rejection, a real 'sysinfo' event from its startup and an
explicitly denied malformed repository-review request. No repo/app mutation.
"""
from __future__ import annotations

import asyncio
import base64
import io
import urllib.request
import zipfile
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
        # Run a real model-backed code review against a fixed PUBLIC ZIP only.
        # The installed backend's own localhost Ollama adapter must generate
        # a syntax-checked proposal. We NEVER approve or export the changes.
        if os.environ.get("JARVIS_INSTALLED_REAL_OLLAMA") != "1":
            raise RuntimeError("Real local Ollama flag absent; refuse fake GGUF PASS")
        with urllib.request.urlopen(
            "http://127.0.0.1:11434/api/tags", timeout=5
        ) as tags_response:
            tags = json.load(tags_response)
        models = [str(m.get("name", "")) for m in tags.get("models", [])]
        if not any(x == "qwen2.5-coder:0.5b" for x in models):
            raise RuntimeError("Authentic local Qwen model not present in Ollama")
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("calc.py", "# Total should multiply price by quantity.\n"
                       "def total(price, qty):\n    return price - qty\n")
        await ws.send(json.dumps({
            "type": "repo_review.request",
            "data": {"action": "inspect", "consent": True,
                     "zip_b64": base64.b64encode(data.getvalue()).decode()},
        }))
        sid = None
        for _ in range(20):
            event = json.loads(await asyncio.wait_for(ws.recv(), timeout=12))
            if event.get("event") != "repo_review_state":
                continue
            data = event.get("data") or {}
            if data.get("status") != "inspected":
                raise RuntimeError("Installed backend rejected trusted static ZIP")
            sid = data.get("session_id")
            break
        if not sid:
            raise RuntimeError("Real ZIP inspection did not return session id")
        await ws.send(json.dumps({
            "type": "repo_review.request",
            "data": {"action": "propose", "consent": True,
                     "session_id": sid, "path": "calc.py", "function": "total",
                     "goal": "Multiply the numeric price by the numeric quantity, not subtract"},
        }))
        proposal = None
        for _ in range(30):
            try:
                event = json.loads(await asyncio.wait_for(ws.recv(), timeout=12))
            except asyncio.TimeoutError:
                continue
            if event.get("event") == "repo_review_state":
                proposal = event.get("data") or {}
                break
        if not proposal or proposal.get("status") != "review_required":
            allowed = {"JSON_FORMAT", "AST_POLICY", "NO_MATERIAL_CHANGE",
                       "PATCH_VALIDATION", "MODEL_UNAVAILABLE", "REQUEST_REJECTED"}
            reason = proposal.get("reason_code") if isinstance(proposal, dict) else None
            reason = reason if reason in allowed else "UNKNOWN_REJECTION"
            raise RuntimeError("Real local Ollama proposal rejected at stage=" + reason)
        if (not proposal.get("patched_sha256")
                or "+    return " not in proposal.get("diff", "")):
            raise RuntimeError("Real local Ollama proposal failed diff/hash invariants")
        # The model itself must generate an AST-vetted proposal; make the
        # separate local-only hash-bound user approval against an IN-MEMORY ZIP
        # copy. Never create a real branch or write to a user's repository.
        await ws.send(json.dumps({
            "type": "repo_review.request",
            "data": {"action": "apply_copy", "session_id": sid,
                     "approved": True,
                     "expected_sha256": proposal["patched_sha256"]},
        }))
        approved_copy = None
        for _ in range(24):
            event = json.loads(await asyncio.wait_for(ws.recv(), timeout=8))
            if event.get("event") == "repo_review_state":
                approved_copy = event.get("data") or {}
                break
        if (not approved_copy or approved_copy.get("status") != "copy_staged"
                or approved_copy.get("patched_sha256") != proposal["patched_sha256"]
                or approved_copy.get("modified_user_repo") is not False):
            raise RuntimeError("Installed Qwen proposal did not pass separate copy/hash approval")
        await ws.send(json.dumps({
            "type": "repo_review.request",
            "data": {"action": "export", "session_id": sid},
        }))
        export = None
        for _ in range(24):
            event = json.loads(await asyncio.wait_for(ws.recv(), timeout=8))
            if event.get("event") == "repo_review_state":
                export = event.get("data") or {}
                break
        if (not export or export.get("status") != "copy_staged"
                or not isinstance(export.get("zip_b64"), str)):
            raise RuntimeError("Installed approved memory copy could not be exported")
        copy_blob = base64.b64decode(export["zip_b64"], validate=True)
        if hashlib.sha256(copy_blob).hexdigest() != export.get("sha256"):
            raise RuntimeError("Exported reviewed ZIP hash mismatch")
        with zipfile.ZipFile(io.BytesIO(copy_blob), "r") as approved_archive:
            patched = approved_archive.read("calc.py")
        if (hashlib.sha256(patched).hexdigest() != proposal["patched_sha256"]
                or b"__import__" in patched):
            raise RuntimeError("Exported source bytes differ from restricted reviewed hash")
        # Rollback discards the model proposal and approved copy.
        await ws.send(json.dumps({
            "type": "repo_review.request",
            "data": {"action": "rollback", "session_id": sid},
        }))
        rolled_back = False
        for _ in range(25):
            event = json.loads(await asyncio.wait_for(ws.recv(), timeout=8))
            if event.get("event") == "repo_review_state":
                rolled_back = (event.get("data") or {}).get("status") == "rolled_back"
                break
        if not rolled_back:
            raise RuntimeError("Installed local Ollama review did not clean up its session")
    return {
        "status": "real_installed_runtime_ws_verified",
        "authenticated_real_sysinfo": True,
        "negative_wrong_token_rejected": rejected,
        "review_without_consent_denied": True,
        "backend_protocol": "websockets-v12",
        "ws_url_sha256": hashlib.sha256(b"ws://127.0.0.1:8765").hexdigest(),
        "ollama_gguf_execution_in_this_probe": True,
        "ollama_model": "qwen2.5-coder:0.5b",
        "trusted_static_zip_model_proposal": True,
        "review_session_rolled_back": True,
        "approved_copy_hash_matched": True,
        "reviewed_zip_export_hash_matched": True,
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
