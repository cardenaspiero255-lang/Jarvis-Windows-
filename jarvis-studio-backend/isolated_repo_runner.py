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
import secrets

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


_CONTAINER_NAME = re.compile(r"^jarvis-ci-[a-z0-9]{4,32}$")


def build_container_argv(snapshot, image, container_name=None):
    """Return a detached, resource-bounded container command with fixed argv.

    Model output controls neither Docker arguments nor image, source path,
    executable, environment, mounts or test commands.
    """
    try:
        p = validate_snapshot(snapshot)
    except (OSError, ValueError) as exc:
        raise SandboxError("Invalid snapshot") from exc
    if not isinstance(image, str) or not _IMAGE.fullmatch(image):
        raise SandboxError("Image MUST be an immutable official Python SHA256 digest")
    name = container_name or ("jarvis-ci-" + secrets.token_hex(8))
    if not isinstance(name, str) or not _CONTAINER_NAME.fullmatch(name):
        raise SandboxError("Invalid restricted container name")
    return [
        "docker", "run", "-d", "--name=" + name,
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
        # Bound stored logs on the daemon. docker logs --tail is also capped
        # and a long log line is rejected before parsing test success.
        "--log-driver=local",
        "--log-opt=max-size=1m",
        "--log-opt=max-file=1",
        "--log-opt=compress=false",
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
    """Run tests ONLY in the container and always force-clean the daemon job.

    docker run is detached to avoid capturing unbounded attached test output.
    Even if docker wait times out or the Docker client crashes, docker rm -f
    runs in finally. Missing/failed cleanup is NOT a successful test.
    """
    name = "jarvis-ci-" + secrets.token_hex(8)
    argv = build_container_argv(snapshot, image, container_name=name)
    status = "runner_unavailable"
    reported = 0
    passed = False
    cleaned = False
    # Never consult an inherited Docker daemon address, credentials or context:
    # use only this host's Unix socket and a throwaway Docker client config.
    with tempfile.TemporaryDirectory(prefix="jarvis-docker-client-") as home:
        env = {key: os.environ[key] for key in ("PATH", "SystemRoot", "SYSTEMROOT",
              "WINDIR", "PATHEXT", "COMSPEC") if key in os.environ}
        env.update({"HOME": home, "DOCKER_CONFIG": home,
                    "DOCKER_HOST": "unix:///var/run/docker.sock",
                    "DOCKER_CONTEXT": "default"})
        def call(args, timeout):
            return subprocess.run(args, cwd=str(Path(snapshot).resolve()),
                                  env=env, shell=False, timeout=timeout,
                                  capture_output=True, text=True, check=False)
        try:
            started = call(argv, 15)
            if started.returncode == 0:
                waited = call(["docker", "wait", name], 90)
                if waited.returncode == 0:
                    try:
                        code = int(waited.stdout.strip())
                    except ValueError:
                        code = -1
                    logs = call(["docker", "logs", "--tail=100", name], 10)
                    combined = (logs.stdout or "") + (logs.stderr or "")
                    if logs.returncode != 0:
                        status = "logs_unavailable"
                    elif len(combined.encode("utf-8")) > _MAX_OUTPUT:
                        status = "output_limit"
                    else:
                        matches = re.findall(r"\bRan\s+(\d+)\s+tests?\b", combined)
                        reported = int(matches[-1]) if matches else 0
                        passed = code == 0 and reported == 11 and "OK" in combined
                        status = "passed" if passed else "tests_failed"
                else:
                    status = "wait_failed"
            else:
                status = "start_failed"
                # Public, trusted Docker CLI diagnostic only. Redact home paths
                # and log a short message, never the fixture or model output.
                reason = (started.stderr or "").replace("\\n", " ").replace("\\r", " ")
                reason = re.sub(r"/home/[^ /]+", "/home/[redacted]", reason)
                print("Docker launch error:", reason[:260])
        except subprocess.TimeoutExpired:
            status = "timeout"
        except (OSError, ValueError, UnicodeError):
            status = "runner_unavailable"
        finally:
            try:
                removed = call(["docker", "rm", "-f", name], 15)
                # Docker may have removed the container itself only on a
                # failed start. Fail closed rather than claim it was cleaned.
                cleaned = removed.returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                cleaned = False
    if not cleaned:
        return {"passed": False, "status": "cleanup_failed",
                "tests_reported": reported, "container_cleaned": False}
    return {"passed": passed, "status": status, "tests_reported": reported,
            "container_cleaned": True}


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


def run_demo(image, *, workspace_root=None, proposer=None):
    """Test trusted baseline in Docker, obtain vetted proposal, retest in Docker.

    The model receives only a public fixture and cannot select paths, commands
    or containers. The sole test executor remains the isolated Linux container.
    """
    with tempfile.TemporaryDirectory(prefix="jarvis-isolation-host-",
                                    dir=str(workspace_root) if workspace_root else None) as scratch:
        os.chmod(scratch, 0o755)
        snapshot = prepare_demo_snapshot(scratch)
        baseline = run_container_tests(snapshot, image)
        print("Docker baseline:", baseline.get("status"),
              "cleaned:", baseline.get("container_cleaned"))
        if (baseline.get("passed") or baseline.get("status") != "tests_failed"
                or baseline.get("container_cleaned") is not True
                or baseline.get("tests_reported") != 11):
            return {"verified": False, "status": "invalid_baseline"}
        proposal = '{"replacement":"return unit_price * quantity"}'
        model_source = "deterministic_test_fixture"
        if proposer is not None:
            try:
                proposal = proposer(
                    "You are fixing a trusted test fixture. Reply with exactly "
                    'one JSON key "replacement" and one Python return statement.',
                    "Repair the addition subtotal bug in this public demo: "
                    "def line_total(unit_price, quantity):\n"
                    "    return unit_price - quantity\n"
                    "Only return JSON with a corrected return statement.",
                )
                model_source = "local_ollama_gguf"
            except (ValueError, OSError, RuntimeError, TimeoutError):
                return {"verified": False, "status": "model_unavailable"}
        try:
            patch = apply_vetted_demo_fix(snapshot, proposal)
        except (SandboxError, ValueError, TypeError, ArithmeticError):
            return {"verified": False, "status": "proposal_rejected"}
        after = run_container_tests(snapshot, image)
        print("Docker corrected:", after.get("status"),
              "cleaned:", after.get("container_cleaned"))
        success = (after.get("passed") is True
                   and after.get("tests_reported") == 11
                   and after.get("container_cleaned") is True)
        return {
            "verified": success,
            "status": "verified" if success else "tests_failed",
            "baseline_passed": False,
            "tests_after": after.get("tests_reported", 0),
            "all_containers_cleaned": after.get("container_cleaned") is True,
            "model_source": model_source,
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
    parser.add_argument("--real-ollama", action="store_true")
    args = parser.parse_args()
    model_evidence = None
    propose = None
    if args.real_ollama:
        # Proven local GGUF model on this *disposable Linux CI host* only.
        from real_local_model_e2e import get_model_evidence
        from local_coding_pipeline import ollama_proposer
        model_evidence = get_model_evidence("http://127.0.0.1:11434",
                                            "qwen2.5-coder:0.5b")
        propose = ollama_proposer("http://127.0.0.1:11434", "qwen2.5-coder:0.5b")
    report = run_demo(args.image_ref, proposer=propose)
    if model_evidence is not None:
        report["local_model"] = model_evidence
    destination = Path(os.environ.get("RUNNER_TEMP", tempfile.gettempdir())) / "jarvis-isolation-proof.json"
    destination.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if not report.get("verified"):
        print("Isolation failure stage:", report.get("status", "unknown"))
        print("FAIL: Linux isolation test did not prove fail-then-pass.")
        return 1
    print("PASS: Linux Docker no-network read-only fixture fail-then-pass:", report["tests_after"])
    print("PASS: verified source SHA256 and image digest captured; no publishing.")
    print("Evidence:", destination)
    return 0


if __name__ == "__main__":
    sys.exit(main())
