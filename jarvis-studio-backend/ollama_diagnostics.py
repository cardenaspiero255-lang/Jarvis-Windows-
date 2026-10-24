"""Bounded, read-only Ollama diagnostics for Windows/offline AI reliability.

Queries only the user's configured local Ollama endpoint by default. An explicit
remote endpoint must use HTTPS; no credentials or arbitrary paths are accepted.
This does not send prompts, generate responses or modify installed models.
"""
from __future__ import annotations

import json
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def _default_get(url):
    request = Request(url, headers={"Accept": "application/json",
                                    "User-Agent": "Jarvis-Windows-local-diagnostics"})
    with urlopen(request, timeout=3.0) as response:
        raw = response.read(250001)
        if len(raw) > 250000:
            raise ValueError("Catalog response is too large.")
        return json.loads(raw)


def _validate_url(url):
    try:
        parts = urlsplit(str(url or "").strip())
        local = parts.hostname in ("localhost", "127.0.0.1", "::1")
        if (parts.scheme not in ("http", "https") or not parts.hostname or
                parts.username is not None or parts.password is not None or
                parts.path not in ("", "/") or parts.query or parts.fragment or
                (parts.scheme == "http" and not local)):
            return ""
        # Avoid leaking raw credentials, invalid user URLs and unsupported schemes.
        return str(url).strip().rstrip("/")
    except ValueError:
        return ""


def diagnose(url, selected="", get_json=None):
    """Check local server/model state; easy to test without a network."""
    base = _validate_url(url)
    if not base:
        return {"ok": False, "reachable": False, "models": [],
                "selected_available": False, "message": (
                    "Invalid Ollama URL. Use http://localhost:11434, "
                    "http://127.0.0.1:11434, or HTTPS for remote servers.")}
    getter = get_json if get_json is not None else _default_get
    try:
        data = getter(base + "/api/tags")
        entries = data.get("models", []) if isinstance(data, dict) else []
        if not isinstance(entries, list):
            raise ValueError("Invalid model listing.")
        models = []
        for entry in entries[:50]:
            if isinstance(entry, dict) and isinstance(entry.get("name"), str):
                value = entry["name"].strip()
                if value and len(value) <= 150 and value not in models:
                    models.append(value)
        models = models[:25]
    except (OSError, ValueError, TypeError, KeyError, TimeoutError):
        return {"ok": False, "reachable": False, "models": [],
                "selected_available": False,
                "message": "Ollama is unavailable or returned an invalid model listing. "
                           "Check that the server is running and reachable."}
    wanted = str(selected or "").strip()
    if wanted.lower().startswith(("ollama:", "local:")):
        wanted = wanted.split(":", 1)[1]
    found = bool(models) and (not wanted or wanted in models)
    if not models:
        msg = "Ollama is reachable but has no installed models. Install a model first."
    elif wanted and wanted not in models:
        msg = f"Ollama is reachable, but the selected model '{wanted[:150]}' is not installed."
    else:
        msg = f"Ollama is reachable with {len(models)} installed model(s)."
    return {"ok": bool(found), "reachable": True, "models": models,
            "selected_available": bool(found), "message": msg}

# A diagnostic inference uses a constant, non-personal prompt. Neither user
# content nor generated text is ever forwarded to cloud models or audit logs.
def _default_post(url, payload):
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json",
                 "User-Agent": "Jarvis-Windows-local-inference-test"},
    )
    with urlopen(request, timeout=12.0) as response:
        raw = response.read(64001)
        if len(raw) > 64000:
            raise ValueError("Ollama probe response exceeds the size limit.")
        return json.loads(raw)


def probe_generation(url, selected="", get_json=None, post_json=None):
    """Prove a selected Ollama model can generate via a bounded API request.

    Unlike a /api/tags catalog check, this verifies a real non-streaming
    /api/generate response. It has a hard network timeout, a token budget and
    a fixed prompt. It returns status/latency only, NEVER generated text.
    Callers MUST enforce user approval before invoking it.
    """
    import time
    from urllib.error import URLError

    base = _validate_url(url)
    model = str(selected or "").strip()
    if model.lower().startswith(("ollama:", "local:")):
        model = model.split(":", 1)[1].strip()
    if not base or not model or len(model) > 150:
        return {"ok": False, "generated": False, "latency_ms": None,
                "message": "Select a valid local Ollama model and endpoint before testing."}
    catalog = diagnose(base, model, get_json=get_json)
    if not catalog["ok"] or not catalog["selected_available"]:
        return {"ok": False, "generated": False, "latency_ms": None,
                "message": "Ollama model unavailable or not installed; no generation attempted."}
    payload = {
        "model": model,
        "prompt": "Return a single word: READY.",
        "stream": False,
        "options": {"temperature": 0, "num_predict": 12},
    }
    send = post_json if post_json is not None else _default_post
    started = time.monotonic()
    try:
        response = send(base + "/api/generate", payload)
        latency = max(0, round((time.monotonic() - started) * 1000))
        if (not isinstance(response, dict) or response.get("done") is not True
                or not isinstance(response.get("response"), str)
                or not response["response"].strip()):
            raise ValueError("Missing completed response.")
    except (OSError, URLError, TimeoutError, ValueError, TypeError):
        return {"ok": False, "generated": False, "latency_ms": None,
                "message": "Ollama inference failed or produced an invalid response."}
    return {"ok": True, "generated": True, "latency_ms": latency,
            "message": "Ollama model generated a nonempty response locally; latency measured."}
