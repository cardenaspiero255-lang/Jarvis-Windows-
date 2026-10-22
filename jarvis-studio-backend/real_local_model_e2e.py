"""Real GGUF-backed Ollama E2E: user command -> model -> vetted patch -> tests.

Only run against a localhost Ollama daemon on a trusted Windows CI runner.
No cloud inference, no arbitrary repository edits or generated code execution.
"""
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

from local_coding_pipeline import execute_coding_task, ollama_proposer

_LOCAL_URL = "http://127.0.0.1:11434"
_MODEL = "qwen2.5-coder:0.5b"
_SHA = re.compile(r"^[a-f0-9]{64}$")


def get_model_evidence(url=_LOCAL_URL, model=_MODEL, fetch=None):
    """Verify locally installed model is GGUF and publish its digest."""
    reader = fetch or (lambda x: json.load(urlopen(x, timeout=8)))
    listing = reader(url + "/api/tags")
    if not isinstance(listing, dict) or not isinstance(listing.get("models"), list):
        raise RuntimeError("No local Ollama model list.")
    matches = [m for m in listing["models"] if m.get("name") == model]
    if len(matches) != 1:
        raise RuntimeError("Required local model is not installed.")
    record = matches[0]
    details = record.get("details") or {}
    digest = str(record.get("digest") or "").lower()
    if str(details.get("format", "")).lower() != "gguf" or not _SHA.fullmatch(digest):
        raise RuntimeError("Model is not a verified local GGUF catalog entry.")
    return {"model": model, "model_digest": digest, "model_format": "gguf",
            "model_family": str(details.get("family") or "")[:40]}


def main():
    url = os.getenv("JARVIS_LOCAL_OLLAMA_URL", _LOCAL_URL)
    model = os.getenv("JARVIS_LOCAL_OLLAMA_MODEL", _MODEL)
    if url != _LOCAL_URL:
        raise RuntimeError("The Windows E2E uses localhost only.")
    evidence = get_model_evidence(url, model)
    with tempfile.TemporaryDirectory(prefix="jarvis-real-model-") as tmp:
        proposer = ollama_proposer(url, model)
        report = execute_coding_task(
            "Jarvis corrige la suma del proyecto de prueba",
            proposer, workspace_root=Path(tmp),
        )
        if (report.get("ok") is not True or report.get("status") != "verified_dry_run"
                or report.get("tests_passed") != 5 or report.get("tests_failed") != 0):
            raise RuntimeError("Model did not complete the vetted programming exercise.")
        content = (Path(report["workspace"]) / "calculator.py").read_bytes()
        if hashlib.sha256(content).hexdigest() != report["sha256"]:
            raise RuntimeError("Vetted result hash mismatch.")
        evidence.update({"source": "real_local_ollama_windows_runner",
                         "verified": True, "tests_passed": 5, "tests_failed": 0,
                         "local_model_latency_ms": report["latency_ms"],
                         "patched_file_sha256": report["sha256"],
                         "workspace_type": "disposable",
                         "modified_user_repository": False,
                         "checked_at": datetime.now(timezone.utc).isoformat()})
    destination = Path(os.getenv("RUNNER_TEMP", ".")) / "jarvis-real-local-model-evidence.json"
    destination.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print("PASS: REAL local Ollama GGUF generated a vetted correction in Windows CI.")
    print("Model:", evidence["model"], "digest:", evidence["model_digest"][:16])
    print("Programming exercise: five verified checks; no user project modified.")
    print("Evidence file:", destination)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as err:
        # No model-generated text, source or raw responses are printed.
        print("FAIL: Real local model E2E did not pass:", type(err).__name__)
        sys.exit(1)
