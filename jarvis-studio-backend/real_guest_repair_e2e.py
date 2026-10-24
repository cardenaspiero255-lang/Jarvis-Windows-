"""Real local Qwen -> review -> VM -> authorized disposable Git CI path.

Only the fixed public teaching fixture. No user-repository execution, no push,
no arbitrary prompt or remote service. Explicit trusted-fixture CLI is required.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

from local_coding_pipeline import ollama_proposer
from trusted_repair_workflow import plan_trusted_repair, execute_trusted_plan, WorkflowBlocked


def demonstrate(rootfs, kernel, *, proposer=None):
    if proposer is None:
        proposer = ollama_proposer("http://127.0.0.1:11434", "qwen2.5-coder:0.5b")
    system = (
        "Return JSON with exactly one key, replacement. Fix ONLY the "
        "return expression in a trusted two-argument math sample. Never return "
        "shell commands, imports or file paths.")
    prompt = (
        "Repair multiplication in the public exercise:\n"
        "def line_total(unit_price, quantity):\n"
        "    return unit_price - quantity\n"
        "Return JSON like {\"replacement\":\"return quantity * unit_price\"}; "
        "only unit_price, quantity and arithmetic are permitted."
    )
    plan = None
    attempts = 0
    for attempt in range(2):
        attempts += 1
        raw = proposer(system, prompt if attempt == 0 else
                       prompt + "\nEarlier proposal failed fixed arithmetic checks.")
        try:
            plan = plan_trusted_repair(raw)
            break
        except WorkflowBlocked:
            continue
    if plan is None:
        raise WorkflowBlocked("Local model proposals rejected; no VM or Git edits")
    # Review stage must not modify any repo. Explicit approval here covers ONLY
    # staging a new, public, disposable local Git fixture branch.
    preview = execute_trusted_plan(plan, approved=False)
    if preview["status"] != "awaiting_explicit_approval":
        raise WorkflowBlocked("Review stage was not read-only")
    result = execute_trusted_plan(plan, approved=True,
                                  vm_rootfs=rootfs, vm_kernel=kernel)
    if result["status"] != "verified_disposable_branch":
        raise WorkflowBlocked("Guest proof or Git staging incomplete")
    return {
        "status": "real_model_guest_and_disposable_git_verified",
        "model": "qwen2.5-coder:0.5b",
        "vm": "qemu-tcg",
        "source_sha256": result["source_sha256"],
        "vm_tests_passed": result["vm_tests_passed"],
        "local_git_tests_passed": result["local_git_tests_passed"],
        "branch_type": "new_disposable_local_only",
        "model_attempts": attempts,
        "modified_files": result["modified_files"],
        "published": False, "modified_user_repo": False,
        "external_repository_execution_authorized": False,
    }


def main():
    parser = argparse.ArgumentParser(description="Trusted real-GGUF + VM + local Git demo")
    parser.add_argument("--trusted-fixture", action="store_true", required=True)
    parser.add_argument("--rootfs", required=True)
    parser.add_argument("--kernel", required=True)
    args = parser.parse_args()
    try:
        report = demonstrate(args.rootfs, args.kernel)
    except (WorkflowBlocked, OSError, RuntimeError, ValueError) as exc:
        print("Real model guest repair failed:", type(exc).__name__)
        return 1
    dest = Path(os.environ.get("RUNNER_TEMP", tempfile.gettempdir())) / "jarvis-model-guest-repair-proof.json"
    dest.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("PASS: real GGUF model patch executed in QEMU TCG and staged in disposable Git.")
    print("VM tests:", report["vm_tests_passed"], "Local Git tests:", report["local_git_tests_passed"])
    print("No external repository, no user file, no publication. Receipt:", dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
