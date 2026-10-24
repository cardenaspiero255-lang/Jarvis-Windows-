"""Fail-closed commercial wake-model release precheck.

This is a technical release gate, NOT legal certification. The published binary
also needs an independent asset inventory and licensing review. Never relax
acoustic benchmark thresholds to pass this check.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sys


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def check_commercial_wake_release(project_root: Path, *, rights_reviewed: str,
                                  expected_sha256: str,
                                  package_engine: str = "legacy_oww") -> dict:
    root = Path(project_root)
    runtime = root / "jarvis-studio-backend/wake_word/openwakeword.py"
    model = root / "jarvis-studio-backend/wake_word/models/hey_jarvis.onnx"
    blockers = []

    if package_engine == "whisper_local":
        # A clean audio-to-text route can use the separately licensed MIT
        # Whisper model without shipping the noncommercial OWW wake weights.
        # Release workflow must still audit the actual FULL package AFTER build.
        hook = root / "jarvis-studio-backend/wake_word/frozen_engine_runtime.py"
        spec = root / "jarvis-studio-backend/jarvis-backend.spec"
        packager = root / "scripts/package-backend.ps1"
        if runtime.is_symlink() or not runtime.is_file() or (
            'engine == "whisper_local"' not in runtime.read_text("utf-8")
            or "LocalWhisperWake" not in runtime.read_text("utf-8")
        ):
            blockers.append("clean_whisper_runtime_missing")
        if hook.is_symlink() or not hook.is_file() or (
            'os.environ["JARVIS_WAKE_ENGINE"] = "whisper_local"'
            not in hook.read_text("utf-8")
        ):
            blockers.append("frozen_whisper_hook_missing")
        if spec.is_symlink() or not spec.is_file() or not all(
            term in spec.read_text("utf-8")
            for term in ("JARVIS_WAKE_PACKAGE_MODE", "runtime_hooks=",
                         "if not clean_wake_bundle:", 'excludes.append("openwakeword")')
        ):
            blockers.append("clean_whisper_spec_missing")
        if packager.is_symlink() or not packager.is_file() or not all(
            term in packager.read_text("utf-8")
            for term in ("JARVIS_WAKE_PACKAGE_MODE", '"whisper_local"',
                         "download_models()", "} else {")
        ):
            blockers.append("clean_whisper_packager_guard_missing")
        if rights_reviewed != "true":
            blockers.append("commercial_rights_not_reviewed")
        return {
            "status": ("NOT_CERTIFIED" if blockers
                       else "COMMERCIAL_WAKE_TECHNICAL_PRECHECK_PASS"),
            "blockers": sorted(set(blockers)),
            "package_engine": package_engine,
            "legal_rights_certified": False,
            "installed_model_certified": False,
            "human_wake_performance_certified": False,
        }
    if package_engine != "legacy_oww":
        blockers.append("unsupported_package_engine")

    # The built-in fallback uses non-commercial pretrained weights. Even a
    # licensed custom model must not silently fall back to these weights.
    if runtime.is_symlink() or not runtime.is_file():
        blockers.append("wake_runtime_missing")
    else:
        source = runtime.read_text(encoding="utf-8")
        if re.search(r"\b(?:return\s+|=\s*)BuiltinInference\s*\(", source):
            blockers.append("noncommercial_builtin_wake_fallback")

    # Source-only approval is not enough if PyInstaller separately fetches or
    # bundles the CC BY-NC-SA pretrained openWakeWord assets. The current
    # production spec and packager both do this, so public release stays blocked.
    spec = root / "jarvis-studio-backend/jarvis-backend.spec"
    packager = root / "scripts/package-backend.ps1"
    if spec.is_symlink() or not spec.is_file():
        blockers.append("pyinstaller_spec_missing")
    else:
        spec_text = spec.read_text(encoding="utf-8")
        if re.search(r"""collect_data_files\s*\(\s*['"]openwakeword['"]""", spec_text):
            blockers.append("noncommercial_openwakeword_data_packaged")
    if packager.is_symlink() or not packager.is_file():
        blockers.append("backend_packager_missing")
    else:
        packager_text = packager.read_text(encoding="utf-8")
        if re.search(r"\bdownload_models\s*\(", packager_text):
            blockers.append("pretrained_openwakeword_weights_downloaded")

    # Explicit owner review is necessary but does not independently prove rights.
    if rights_reviewed != "true":
        blockers.append("commercial_rights_not_reviewed")
    if not isinstance(expected_sha256, str) or not _SHA256.fullmatch(expected_sha256):
        blockers.append("approved_model_hash_missing")

    if model.is_symlink() or not model.is_file():
        blockers.append("approved_model_missing")
    elif model.stat().st_size < 100_000:
        blockers.append("approved_model_too_small")
    elif _SHA256.fullmatch(expected_sha256 or ""):
        with model.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        if digest != expected_sha256:
            blockers.append("approved_model_hash_mismatch")

    return {
        "status": "NOT_CERTIFIED" if blockers else "COMMERCIAL_WAKE_TECHNICAL_PRECHECK_PASS",
        "blockers": sorted(set(blockers)),
        "legal_rights_certified": False,
        "installed_model_certified": False,
        "human_wake_performance_certified": False,
    }


def main() -> int:
    report = check_commercial_wake_release(
        Path(__file__).resolve().parent.parent,
        rights_reviewed=os.environ.get("WAKE_MODEL_COMMERCIAL_RIGHTS_REVIEWED", ""),
        expected_sha256=os.environ.get("WAKE_MODEL_APPROVED_SHA256", ""),
        package_engine=os.environ.get("JARVIS_WAKE_PACKAGE_MODE", "legacy_oww"),
    )
    print("COMMERCIAL_WAKE_RELEASE_PRECHECK=" + json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "COMMERCIAL_WAKE_TECHNICAL_PRECHECK_PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
