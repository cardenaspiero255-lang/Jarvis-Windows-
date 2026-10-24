"""Build-stage FULL offline bundle inspection; no installation claims.

Scans staged Tauri backend resources BEFORE installer construction.
Does not prove voice-model legal rights, signature or a physical Windows E2E.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ENGINE = "whisper_local"
VOICE = "en_GB-alan-medium"


def audit_full_bundle(root: Path, *, engine: str) -> dict:
    root = Path(root).resolve()
    blockers = []
    hashes = {}

    if engine != ENGINE:
        blockers.append("not_licensed_wake_engine")

    def regular(path: Path, issue: str, min_size: int = 1) -> bool:
        if path.is_symlink() or not path.is_file() or path.stat().st_size < min_size:
            blockers.append(issue)
            return False
        with path.open("rb") as fh:
            hashes[str(path.relative_to(root)).replace("\\", "/")] = hashlib.file_digest(fh, "sha256").hexdigest()
        return True

    regular(root / "jarvis-backend.exe", "backend_executable_missing", 100000)
    preload = root / "preload-assets"
    regular(preload / "whisper-base" / "model.bin", "whisper_model_missing", 100000)
    config = preload / "whisper-base" / "config.json"
    if config.is_symlink() or not config.is_file() or not config.read_bytes().strip():
        blockers.append("whisper_config_missing")
    regular(preload / "piper" / (VOICE + ".onnx"), "piper_voice_missing", 100000)
    cfg = preload / "piper" / (VOICE + ".onnx.json")
    if cfg.is_symlink() or not cfg.is_file() or not cfg.read_bytes().strip():
        blockers.append("piper_voice_config_missing")

    chrome = sorted((preload / "ms-playwright").glob("chromium-*/chrome-win*/chrome.exe"))
    if len(chrome) != 1 or not regular(chrome[0], "chromium_missing", 100000):
        if not chrome:
            blockers.append("chromium_missing")
        elif len(chrome) > 1:
            blockers.append("ambiguous_chromium_binaries")

    # A packaged NC model (even unused) makes public distribution incompatible
    # with a clean licensing claim. This is intentionally broader than a name
    # check for hey_jarvis and inspects nested PyInstaller data directories.
    forbidden = []
    for candidate in root.rglob("*"):
        try:
            rel = candidate.relative_to(root)
            parts = [part.lower() for part in rel.parts]
            is_model = candidate.suffix.lower() in (".onnx", ".tflite", ".pb", ".h5")
            if candidate.is_symlink():
                blockers.append("bundle_symlink_detected")
            if is_model and ("openwakeword" in parts or
                             any(part.startswith("hey_jarvis") for part in parts)):
                forbidden.append(str(rel).replace("\\", "/"))
        except (OSError, ValueError):
            blockers.append("asset_scan_failed")
    if forbidden:
        blockers.append("restricted_openwakeword_assets_present")

    return {
        "schema": "jarvis-full-offline-asset-preflight-v1",
        "status": "FULL_ASSETS_PRESENT_NOT_CERTIFIED" if not blockers else "BLOCKED",
        "engine": engine,
        "blockers": sorted(set(blockers)),
        "hashes": hashes if not blockers else {},
        "forbidden_model_files_count": len(forbidden),
        "installed_full_runtime_certified": False,
        "license_rights_certified": False,
        "code_signature_certified": False,
        "physical_microphone_certified": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--engine", default=ENGINE)
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()
    result = audit_full_bundle(args.bundle, engine=args.engine)
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(result, indent=2, sort_keys=True), "utf-8")
    print("JARVIS_FULL_ASSET_PREFLIGHT=" + json.dumps({
        "status": result["status"], "blockers": result["blockers"],
        "checked_assets": len(result["hashes"]),
        "installed_full_runtime_certified": False,
    }, sort_keys=True))
    return 0 if not result["blockers"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
