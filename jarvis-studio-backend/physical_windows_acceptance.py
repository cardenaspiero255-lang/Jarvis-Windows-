"""Fail-closed policy for user-observed Windows physical acceptance.

This module validates the structure of a local operator receipt. It cannot
independently prove sound was captured or heard; no synthetic result certifies
physical audio, and no external approval is implied.
"""
from __future__ import annotations

import json
import re
import sys

REQUIRED_CASES = (
    "mic_stt",
    "wake_word",
    "tts_audible",
    "permission_denial",
    "permission_safe_approval",
    "cancel_listening",
    "cancel_speaking",
    "cancel_readonly_task",
    "recover_relaunch",
    "recover_microphone_access",
)


def evaluate(receipt: object) -> dict:
    """Never infer a physical result from CI, stale tests or missing claims."""
    data = receipt if isinstance(receipt, dict) else {}
    blockers = []
    if data.get("schema") != "jarvis-windows-physical-v1":
        blockers.append("schema")
    if data.get("platform") != "windows":
        blockers.append("platform")
    if data.get("host_type") != "physical_observed":
        blockers.append("host_type")
    if data.get("source") != "interactive_operator":
        blockers.append("source")
    if data.get("gui_process_observed") is not True:
        blockers.append("gui_process_observed")
    if data.get("audio_adapter_detected") is not True:
        blockers.append("audio_adapter_detected")
    sha = data.get("gui_exe_sha256")
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", sha):
        blockers.append("gui_exe_sha256")

    cases = data.get("cases")
    if not isinstance(cases, list):
        cases = []
    case_ids = [case.get("id") for case in cases if isinstance(case, dict)]
    if (len(case_ids) != len(REQUIRED_CASES)
            or len(set(k for k in case_ids if isinstance(k, str))) != len(REQUIRED_CASES)
            or set(k for k in case_ids if isinstance(k, str)) != set(REQUIRED_CASES)):
        blockers.append("case_inventory")
    for case_id in REQUIRED_CASES:
        matches = [case for case in cases if isinstance(case, dict)
                   and case.get("id") == case_id]
        if (len(matches) != 1 or matches[0].get("outcome") != "pass"
                or matches[0].get("evidence_mode") != "human_observed"):
            blockers.append("case:" + case_id)

    return {
        "schema": "jarvis-windows-physical-adjudication-v1",
        "status": "NOT_CERTIFIED" if blockers else "USER_ATTESTED_PHYSICAL",
        "blockers": sorted(set(blockers)),
        "cases_required": len(REQUIRED_CASES),
        "cases_received": len(cases),
        # A self-reported interactive receipt is not independent acoustic
        # instrumentation, signed lab evidence, or third-party certification.
        "physical_certified": False,
        "independently_certified": False,
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: python physical_windows_acceptance.py <receipt.json>", file=sys.stderr)
        return 2
    try:
        with open(argv[1], "r", encoding="utf-8-sig") as stream:
            receipt = json.load(stream)
    except (OSError, ValueError):
        receipt = None
    report = evaluate(receipt)
    print(json.dumps(report, sort_keys=True, ensure_ascii=False))
    return 0 if report["status"] == "USER_ATTESTED_PHYSICAL" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
