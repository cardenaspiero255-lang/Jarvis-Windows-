"""Fixed trusted fixture: review -> real VM proof -> authorized local Git staging.

NEVER run external repository code. This intentionally only supports the
checked-in arithmetic teaching fixture. No publication, remote, user path or
shell command can be provided via model output or approval.
"""
from __future__ import annotations

import ast
import difflib
import hashlib
import json
import subprocess

from controlled_repository_agent import (
    _evaluate, _expression, _TASKS, repair_controlled_repository
)
from local_coding_pipeline import parse_proposal, CodingTaskError
from qemu_tcg_guest import run_vm_fixture, VMGuestError


class WorkflowBlocked(PermissionError):
    pass


_ORIGINAL = "def line_total(unit_price, quantity):\n    return unit_price - quantity\n"
_TESTS = _TASKS["total"]["tests"]


def plan_trusted_repair(model_response):
    """Prepare only a source digest and review diff; no disk/network/VM/Git."""
    try:
        candidate = parse_proposal(model_response)
        expr = _expression(candidate, ("unit_price", "quantity"))
        if any(_evaluate(expr, {"unit_price": x, "quantity": y}) != expected
               for x, y, expected in _TESTS):
            raise WorkflowBlocked("Proposed change does not pass bounded arithmetic oracle")
    except (CodingTaskError, TypeError, ArithmeticError, ValueError) as exc:
        raise WorkflowBlocked("Unsafe or invalid local model proposal") from exc
    source = "def line_total(unit_price, quantity):\n    return " + ast.unparse(expr) + "\n"
    sha = hashlib.sha256(source.encode("utf-8")).hexdigest()
    diff = "".join(difflib.unified_diff(
        _ORIGINAL.splitlines(keepends=True),
        source.splitlines(keepends=True),
        fromfile="before/src/totals.py", tofile="after/src/totals.py",
    ))
    if not diff:
        raise WorkflowBlocked("Model proposed no change")
    return {
        "status": "review_required",
        "model_response": model_response,
        "source": source,
        "source_sha256": sha,
        "modified_files": ["src/totals.py"],
        "diff": diff,
        "verification": "static_arithmetic_only",
        "external_repository_execution_allowed": False,
        "modified_user_repo": False,
        "published": False,
    }


def execute_trusted_plan(plan, *, approved=False, vm_rootfs=None, vm_kernel=None):
    """Approval gates all execution and Git writes; VM proves exact patch bytes."""
    if not isinstance(plan, dict) or not isinstance(plan.get("model_response"), str):
        raise WorkflowBlocked("Missing immutable trusted fixture plan")
    fresh = plan_trusted_repair(plan["model_response"])
    for key in ("source", "source_sha256", "modified_files", "diff"):
        if plan.get(key) != fresh[key]:
            raise WorkflowBlocked("Review plan was modified after generation")
    if approved is not True:
        return {
            "status": "awaiting_explicit_approval",
            "source_sha256": fresh["source_sha256"],
            "modified_user_repo": False, "published": False,
        }
    if not vm_rootfs or not vm_kernel:
        raise WorkflowBlocked("Verified guest environment is required")
    try:
        receipt = run_vm_fixture(
            rootfs=vm_rootfs, kernel=vm_kernel,
            source=fresh["source"].encode("utf-8"),
            expected_source_sha256=fresh["source_sha256"],
        )
    except (VMGuestError, OSError, subprocess.SubprocessError) as exc:
        raise WorkflowBlocked("Trusted guest execution failed; no Git edit allowed") from exc
    if (receipt.get("verified") is not True
            or receipt.get("status") != "trusted_fixture_guest_verified"
            or receipt.get("source_sha256") != fresh["source_sha256"]
            or receipt.get("guest_tests_passed") != 7
            or receipt.get("user_repository_modified") is not False
            or receipt.get("publication") != "none"
            or receipt.get("external_repository_execution_authorized") is not False):
        raise WorkflowBlocked("Guest receipt is incomplete or inconsistent")
    staged = repair_controlled_repository(
        "JARVIS corrige el total del repositorio de prueba",
        lambda _system, _prompt: fresh["model_response"],
    )
    if (staged.get("ok") is not True or staged.get("status") != "verified_local_branch"
            or staged.get("source_sha256") != fresh["source_sha256"]
            or staged.get("modified_files") != ["src/totals.py"]
            or staged.get("published") is not False
            or staged.get("modified_user_repo") is not False
            or staged.get("tests_passed") != 7):
        raise WorkflowBlocked("Disposable Git staging failed; no publication allowed")
    return {
        "status": "verified_disposable_branch",
        "branch": staged["branch"],
        "source_sha256": fresh["source_sha256"],
        "vm_tests_passed": 7,
        "local_git_tests_passed": staged["tests_passed"],
        "modified_files": ["src/totals.py"],
        "modified_user_repo": False, "published": False,
        "external_repository_execution_allowed": False,
    }
