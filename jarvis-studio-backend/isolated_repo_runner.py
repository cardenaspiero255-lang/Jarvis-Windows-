"""Linux Docker isolation harness for a trusted multi-module test fixture.

This module NEVER imports, tests or executes project Python on the host.
It only copies an allowlisted local fixture and runs its tests in a
read-only, no-network, non-root, resource-limited Docker container.

SECURITY SCOPE: a Docker container shares its Linux host kernel. This is
defense in depth on a disposable GitHub-hosted Linux runner, NOT a proven
strong isolation boundary for arbitrary hostile projects or secrets.
Do not run this harness on the Windows desktop or expose a general code
execution action to the JARVIS language model.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from controlled_repository_agent import _evaluate, _expression
from local_coding_pipeline import CodingTaskError, parse_proposal

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "isolation_repo"
_FILES = (
    "README.md",
    "src/pricing.py",
    "src/coupons.py",
    "src/orders.py",
    "tests/test_checkout.py",
    "tests/test_isolation.py",
)
_IMAGE = re.compile(r"^(?:docker\.io/library/)?python@sha256:[a-f0-9]{64}$")
_MAX_FILES = 40
_MAX_SIZE = 2 * 1024 * 1024
_MAX_INDIVIDUAL = 256 * 1024
_MAX_OUTPUT = 4000
_CHECKS = ((0, 0, 0), (1, 1, 1), (3, 5, 15), (10, 0, 0),
           (13, 2, 26), (7, 9, 63), (125, 4, 500))


class SandboxError(ValueError):
    pass


def validate_snapshot(snapshot):
    """Reject links, metadata and oversized snapshots before Docker mount."""
    raw_path = Path(snapshot)
    if raw_path.is_symlink():
        raise SandboxError("Snapshot cannot be a symlink")
    p = raw_path.resolve(strict=True)
    if not p.is_dir():
        raise SandboxError("Snapshot must be a real directory")
    count, total = 0, 0
    for base, dirs, files in os.walk(p, followlinks=False):
        root = Path(base)
        for name in dirs:
            entry = root / name
            if (name.startswith(".") or entry.is_symlink()
                    or not entry.is_dir()):
                raise SandboxError("Unsafe snapshot directory")
        for name in files:
            entry = root / name
            count += 1
            if (name.startswith(".") or entry.is_symlink()
                    or not entry.is_file() or entry.suffix not in (".py", ".md")):
                raise SandboxError("Unsafe snapshot file")
            length = entry.stat().st_size
            total += length
            if length > _MAX_INDIVIDUAL or count > _MAX_FILES or total > _MAX_SIZE:
                raise SandboxError("Snapshot exceeds fixed input limits")
    if count == 0:
        raise SandboxError("Empty snapshot")
    return p


def prepare_demo_snapshot(parent):
    """Copy explicitly named checked-in files; never follow untrusted links."""
    base = Path(parent).resolve(strict=True)
    if not base.is_dir() or base.is_symlink():
        raise SandboxError("Invalid temporary workspace")
    target = Path(tempfile.mkdtemp(prefix="jarvis-isolated-", dir=str(base)))
    os.chmod(target, 0o755)
    for filename in _FILES:
        source = _FIXTURE.joinpath(*filename.split("/"))
        if source.is_symlink() or not source.is_file():
            raise SandboxError("Controlled fixture is missing or symlinked")
        raw = source.read_bytes()
        if len(raw) > _MAX_INDIVIDUAL:
            raise SandboxError("Controlled fixture exceeds size cap")
        destination = target.joinpath(*filename.split("/"))
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(destination.parent, 0o755)
        destination.write_bytes(raw.replace(b"\r\n", b"\n"))
        os.chmod(destination, 0o644)
    validate_snapshot(target)
    return target


def build_container_argv(snapshot, image):
    """Produce one fixed Docker argv; only snapshot and pinned digest vary."""
    try:
        p = validate_snapshot(snapshot)
    except (OSError, ValueError) as exc:
        raise SandboxError("Invalid snapshot") from exc
    if not isinstance(image, str) or not _IMAGE.fullmatch(image):
        raise SandboxError("Image MUST be an immutable official Python SHA256 digest")
    return [
        "docker", "run", "--rm",
        "--pull=never",
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--pids-limit=64",
        "--memory=256m",
        "--memory-swap=256m",
        "--cpus=1",
        "--user=65534:65534",
        "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=16m",
        "--ulimit=nofile=64:64",
        "--mount=type=bind,source=" + str(p) + ",target=/code,readonly",
        "--workdir=/code",
        "--env=PYTHONPATH=/code/src",
        "--env=PYTHONDONTWRITEBYTECODE=1",
        "--env=HOME=/tmp",
        image,
        "python", "-B", "-m", "unittest", "discover",
        "-s", "/code/tests", "-p", "test_*.py", "-v",
    ]


def run_container_tests(snapshot, image):
    """Docker is the ONLY executor. No test imports or child shell on the host."""
    argv = build_container_argv(snapshot, image)
    # No inherited GITHUB_TOKEN, DOCKER_HOST, DOCKER_CONFIG, AWS_* or model keys.
    env = {name: os.environ[name] for name in (
        "PATH", "SystemRoot", "SYSTEMROOT", "WINDIR", "PATHEXT", "COMSPEC"
    ) if name in os.environ}
    try:
        outcome = subprocess.run(
            argv, cwd=str(Path(snapshot).resolve()), env=env,
            shell=False, timeout=90, capture_output=True, text=True,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"passed": False, "status": "timeout", "tests_reported": 0}
    except (OSError, ValueError):
        return {"passed": False, "status": "runner_unavailable", "tests_reported": 0}
    combined = (outcome.stdout or "")[-_MAX_OUTPUT:] + (outcome.stderr or "")[-_MAX_OUTPUT:]
    seen = re.findall(r"\bRan\s+(\d+)\s+tests?\b", combined)
    count = int(seen[-1]) if seen else 0
    return {"passed": outcome.returncode == 0 and count >= 11,
            "status": "passed" if outcome.returncode == 0 and count >= 11
                      else "tests_failed",
            "tests_reported": count}


def apply_vetted_demo_fix(snapshot, raw_proposal):
    """Validate a single pricing return expression and write only its source."""
    p = validate_snapshot(snapshot)
    candidate = p / "src" / "pricing.py"
    expected = b"def line_total(unit_price, quantity):\n    return unit_price - quantity\n"
    if candidate.is_symlink() or candidate.read_bytes() != expected:
        raise SandboxError("Unrecognized or previously modified demo source")
    try:
        text = parse_proposal(raw_proposal)
        expr = _expression(text, ("unit_price", "quantity"))
    except CodingTaskError as exc:
        raise SandboxError("Rejected unsafe model proposal") from exc
    if not all(_evaluate(expr, {"unit_price": a, "quantity": b}) == expected
               for a, b, expected in _CHECKS):
        raise SandboxError("Proposal does not pass fixed arithmetic checks")
    # Model code is not executed on the host: AST arithmetic is interpreted by
    # a narrowly constrained evaluator already regression-tested separately.
    fixed = b"def line_total(unit_price, quantity):\n    return unit_price * quantity\n"
    candidate.write_bytes(fixed)
    return {
        "modified_files": ["src/pricing.py"],
        "sha256": hashlib.sha256(fixed).hexdigest(),
    }


def run_demo(image, *, workspace_root=None):
    """Fail-first then pass with known-safe edit entirely tested inside Docker."""
    with tempfile.TemporaryDirectory(prefix="jarvis-isolation-host-",
                                    dir=str(workspace_root) if workspace_root else None) as scratch:
        os.chmod(scratch, 0o755)
        snapshot = prepare_demo_snapshot(scratch)
        baseline = run_container_tests(snapshot, image)
        if baseline["passed"] or baseline["status"] != "tests_failed":
            return {"verified": False, "status": "invalid_baseline"}
        patch = apply_vetted_demo_fix(
            snapshot, '{"replacement":"return unit_price * quantity"}')
        after = run_container_tests(snapshot, image)
        return {
            "verified": after["passed"] and after["tests_reported"] == 11,
            "status": "verified" if after["passed"] and after["tests_reported"] == 11
                      else "tests_failed",
            "baseline_passed": baseline["passed"],
            "tests_after": after["tests_reported"],
            "modified_files": patch["modified_files"],
            "source_sha256": patch["sha256"],
            "execution_platform": "linux_docker_not_windows",
            "network": "none", "read_only_source": True, "publication": "none",
            "image": image,
        }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Isolated trusted fixture test")
    parser.add_argument("--ci-demo", action="store_true", required=True)
    parser.add_argument("--image-ref", required=True)
    args = parser.parse_args()
    report = run_demo(args.image_ref)
    destination = Path(os.environ.get("RUNNER_TEMP", tempfile.gettempdir())) / "jarvis-isolation-proof.json"
    destination.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if not report.get("verified"):
        print("FAIL: Linux isolation test did not prove fail-then-pass.")
        return 1
    print("PASS: Linux Docker no-network read-only fixture fail-then-pass:", report["tests_after"])
    print("PASS: verified source SHA256 and image digest captured; no publishing.")
    print("Evidence:", destination)
    return 0


if __name__ == "__main__":
    sys.exit(main())
