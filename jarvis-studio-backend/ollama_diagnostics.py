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
