"""Fail-closed microVM capability probe and untrusted-code execution gate.

This module deliberately does NOT launch guests or execute repositories.
Having /dev/kvm, Docker, an environment variable or user approval is not
evidence of an isolated guest boot. A vetted VM executor must be implemented
and independently tested before any untrusted tests can be enabled.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys
import tempfile


class VMExecutionBlocked(PermissionError):
    pass


def probe_vm_capability(*, platform=None, kvm_path="/dev/kvm"):
    """Inspect device readiness; NEVER claim guest certification."""
    host = sys.platform if platform is None else platform
    available = False
    if host.startswith("linux"):
        try:
            info = os.stat(kvm_path, follow_symlinks=False)
            available = stat.S_ISCHR(info.st_mode) and os.access(
                kvm_path, os.R_OK | os.W_OK)
        except OSError:
            pass
    if not host.startswith("linux"):
        reason = "requires_linux_kvm_host"
    elif not available:
        reason = "kvm_device_missing_or_inaccessible"
    else:
        reason = "kvm_available_but_no_verified_guest_boot"
    return {
        "host_family": "linux" if host.startswith("linux") else "unsupported",
        "kvm_available": bool(available),
        "guest_boot_verified": False,
        "untrusted_execution_allowed": False,
        "reason": reason,
        "trust_boundary": "untrusted_external_code_execution_is_disabled",
    }


def require_verified_vm(capability, *, user_approved=False):
    """Permanent deny until a separate real VM executor and proof are integrated.

    Caller-provided booleans and cached JSON receipts are not trusted as a
    guest attestation. Approval is necessary, never sufficient.
    """
    raise VMExecutionBlocked(
        "Untrusted repository test execution denied: no attested microVM executor")


def write_capability_receipt(destination, capability):
    """Emit strictly allowlisted, non-secret machine-readiness evidence."""
    target = Path(destination)
    if not target.parent.is_dir():
        raise ValueError("Capability receipt parent directory does not exist")
    safe = {
        "host_family": capability.get("host_family", "unknown"),
        "kvm_available": bool(capability.get("kvm_available", False)),
        "guest_boot_verified": False,
        "untrusted_execution_allowed": False,
        "reason": str(capability.get("reason", "unknown"))[:80],
    }
    target.write_text(json.dumps(safe, indent=2) + "\n", encoding="utf-8")
    return str(target)


def main():
    parser = argparse.ArgumentParser(description="Probe KVM but never enable code execution")
    parser.add_argument("--ci-probe", action="store_true", required=True)
    args = parser.parse_args()
    assert args.ci_probe
    report = probe_vm_capability()
    folder = Path(os.environ.get("RUNNER_TEMP", tempfile.gettempdir()))
    location = write_capability_receipt(folder / "jarvis-vm-capability.json", report)
    print("MicroVM capability:", report["reason"])
    print("External repository test execution: DENIED (no verified guest boot)")
    print("Receipt:", location)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
