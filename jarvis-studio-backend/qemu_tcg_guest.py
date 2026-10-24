"""QEMU software-emulated guest proof for *pinned, trusted* Python arithmetic fixtures.

This is NOT a general external-repository execution service. No user-supplied
repository, dependency installer, VM argv, kernel path or guest command is
accepted. The only executed Python inside the disposable guest is a checked,
two-line arithmetic fixture. Guest receipt proves a model-proposed source
digest was tested by a distinct Linux VM (TCG; no /dev/kvm required).

A QEMU VM is a stronger separation than Docker sharing the runner kernel,
but does NOT certify containment against truly malicious guest workloads.
"""
from __future__ import annotations

import ast
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import tempfile

from controlled_repository_agent import _evaluate, _expression
from isolated_repo_runner import _CHECKS
from local_coding_pipeline import CodingTaskError


class VMGuestError(ValueError):
    pass


def _validate_source(source):
    if not isinstance(source, bytes) or len(source) > 512 or b"\r" in source:
        raise VMGuestError("Only a small, canonical trusted Python fixture is allowed")
    header = b"def line_total(unit_price, quantity):\n    "
    if not source.startswith(header) or not source.endswith(b"\n") or source.count(b"\n") != 2:
        raise VMGuestError("Source must contain exactly one return in fixed fixture")
    expression = source[len(header):-1].decode("ascii", "strict")
    try:
        parsed = _expression(expression, ("unit_price", "quantity"))
        if source != (header + ("return " + ast.unparse(parsed)).encode("ascii") + b"\n"):
            raise VMGuestError("Source must be reconstructed from validated AST")
        for a, b, expected in _CHECKS:
            actual = _evaluate(parsed, {"unit_price": a, "quantity": b})
            if actual != expected:
                raise VMGuestError("Arithmetic proposal fails fixed checks")
    except (CodingTaskError, ArithmeticError, ValueError, UnicodeError) as exc:
        raise VMGuestError("Rejected fixture before guest execution") from exc
    return hashlib.sha256(source).hexdigest()


def stage_vm_guest(rootfs, source, nonce):
    """Add a *single* trusted Python exercise to a prebuilt trusted OCI rootfs."""
    root = Path(rootfs).resolve(strict=True)
    if not root.is_dir() or not re.fullmatch(r"[a-zA-Z0-9_-]{4,64}", nonce):
        raise VMGuestError("Invalid guest workspace or nonce")
    python = "/usr/local/bin/python3"
    if not (root / python.lstrip("/")).exists():
        python = "/usr/bin/python3"
    if not (root / python.lstrip("/")).exists() or not (root / "bin").is_dir():
        raise VMGuestError("Pinned trusted Python guest rootfs is not prepared")
    digest = _validate_source(source)
    work = root / "work"
    work.mkdir(mode=0o755, exist_ok=True)
    (work / "pricing.py").write_bytes(source)
    code = (
        "import hashlib\n"
        "from pathlib import Path\n"
        "original = Path('/work/pricing.py').read_bytes()\n"
        "expected = " + repr(digest) + "\n"
        "if hashlib.sha256(original).hexdigest() != expected: raise SystemExit(11)\n"
        "scope = {}\n"
        "exec(compile(original, '/work/pricing.py', 'exec'), scope, scope)\n"
        "fn = scope['line_total']\n"
        "cases = [(0,0,0),(1,1,1),(3,5,15),(10,0,0),"
        "(13,2,26),(7,9,63),(125,4,500)]\n"
        "for a,b,want in cases:\n"
        "    if fn(a,b) != want: raise SystemExit(12)\n"
        "print('JARVIS_VM_GUEST:" + nonce + ":PASS:" + digest + "', flush=True)\n"
    )
    (work / "guest_tests.py").write_text(code, encoding="ascii")
    boot = (
        "#!/bin/sh\n"
        "export PATH=/bin:/usr/bin:/usr/local/bin\n"
        "mkdir -p /proc /sys /dev\n"
        "mount -t devtmpfs devtmpfs /dev 2>/dev/null || true\n"
        "mount -t proc proc /proc 2>/dev/null || true\n"
        "mount -t sysfs sysfs /sys 2>/dev/null || true\n"
        "echo JARVIS_VM_INIT_STARTED > /dev/ttyS0\n"
        + python + " -I -B /work/guest_tests.py > /dev/ttyS0 2>&1\n"
        "status=$?\n"
        "if [ \"$status\" -ne 0 ]; then echo JARVIS_VM_TEST_FAILED > /dev/ttyS0; fi\n"
        "/bin/busybox poweroff -f\n"
        "exit 1\n"
    )
    (root / "init").write_text(boot, encoding="ascii")
    (root / "init").chmod(0o755)
    return {"source_sha256": digest, "nonce": nonce, "runtime": python}


def build_qemu_argv(kernel, initrd):
    k = Path(kernel)
    i = Path(initrd)
    if not k.is_file() or not i.is_file() or k.is_symlink() or i.is_symlink():
        raise VMGuestError("Kernel and sealed guest initramfs are required")
    return [
        "qemu-system-x86_64",
        "-machine", "pc", "-accel", "tcg", "-cpu", "max",
        "-m", "512M", "-smp", "1",
        "-kernel", str(k.resolve()),
        "-initrd", str(i.resolve()),
        "-append", "console=ttyS0 rdinit=/init panic=1 quiet",
        "-nographic", "-monitor", "none", "-serial", "stdio",
        "-nic", "none", "-no-reboot", "-no-user-config", "-nodefaults",
    ]


def verify_serial_receipt(output, nonce, expected_sha256):
    if not isinstance(output, str) or len(output) > 128000:
        raise VMGuestError("Unbounded guest console")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{4,64}", nonce):
        raise VMGuestError("Invalid challenge nonce")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise VMGuestError("Invalid expected source digest")
    marker = "JARVIS_VM_GUEST:" + nonce + ":PASS:" + expected_sha256
    count = sum(line.strip() == marker for line in output.splitlines())
    if count != 1 or "JARVIS_VM_TEST_FAILED" in output:
        raise VMGuestError("Guest did not attest successful execution of patched source")
    return True


def _pack_cpio(root):
    """Pack trusted, prebuilt OCI rootfs into a disposable compressed initramfs."""
    with tempfile.NamedTemporaryFile(prefix="jarvis-qemu-", suffix=".cpio.gz",
                                     delete=False) as holder:
        output = Path(holder.name)
    try:
        paths = []
        for base, dirs, files in os.walk(root, followlinks=False):
            rel = Path(base).relative_to(root)
            for name in sorted(dirs + files):
                item = rel / name
                paths.append("./" + item.as_posix())
        payload = b"\x00".join(p.encode("utf-8") for p in paths) + b"\x00"
        with tempfile.TemporaryFile() as archive:
            subprocess.run(
                ["cpio", "--null", "--create", "--format=newc", "--quiet"],
                input=payload, stdout=archive, cwd=str(root),
                check=True, timeout=40)
            archive.seek(0)
            with gzip.open(output, "wb", compresslevel=1) as zipped:
                while True:
                    part = archive.read(1024 * 1024)
                    if not part:
                        break
                    zipped.write(part)
        if output.stat().st_size > 90 * 1024 * 1024:
            raise VMGuestError("Guest initramfs exceeds configured limit")
        return output
    except BaseException:
        output.unlink(missing_ok=True)
        raise


def launch_guest(argv, *, timeout=120):
    """QEMU serial output is capped on disk, and timeout kills the process group."""
    with tempfile.TemporaryFile() as log:
        proc = subprocess.Popen(
            argv, stdin=subprocess.DEVNULL, stdout=log,
            stderr=subprocess.STDOUT, start_new_session=True)
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=10)
            raise VMGuestError("Guest boot/test timeout") from exc
        log.seek(0)
        raw = log.read(128001)
    if len(raw) > 128000:
        raise VMGuestError("Guest serial output exceeds cap")
    return code, raw.decode("utf-8", errors="replace")


def run_vm_fixture(*, rootfs, kernel, source, expected_source_sha256):
    """Run a fixed arithmetic exercise inside QEMU TCG; never user repo code."""
    digest = _validate_source(source)
    if digest != expected_source_sha256:
        raise VMGuestError("Source SHA-256 differs from reviewed patch")
    if not Path(kernel).is_file():
        raise VMGuestError("Kernel unavailable")
    nonce = secrets.token_hex(12)
    stage = stage_vm_guest(rootfs, source, nonce)
    image = _pack_cpio(Path(rootfs).resolve())
    try:
        argv = build_qemu_argv(kernel, image)
        code, output = launch_guest(argv)
        # QEMU shutdown normally exits zero. A positive guest receipt is
        # mandatory even if QEMU itself exits successfully.
        if code != 0:
            raise VMGuestError("QEMU exited with nonzero status")
        try:
            verify_serial_receipt(output, nonce, digest)
        except VMGuestError:
            # Only the public, fixed fixture is ever booted here. Show
            # bounded serial diagnostics to locate boot/runtime failures.
            print("QEMU guest serial tail (trusted fixture only):")
            print(output[-3800:])
            raise
        return {
            "verified": True, "status": "trusted_fixture_guest_verified",
            "source_sha256": stage["source_sha256"],
            "runtime": "qemu-system-x86_64",
            "accelerator": "tcg", "guest_tests_passed": 7,
            "guest_network": "none", "host_shares": "none",
            "user_repository_modified": False, "publication": "none",
            "external_repository_execution_authorized": False,
            "image_sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
        }
    finally:
        image.unlink(missing_ok=True)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Trusted fixture guest proof only")
    parser.add_argument("--trusted-fixture", action="store_true", required=True)
    parser.add_argument("--rootfs", required=True)
    parser.add_argument("--kernel", required=True)
    parser.add_argument("--source-file", required=True)
    parser.add_argument("--source-sha256", required=True)
    args = parser.parse_args()
    source = Path(args.source_file).read_bytes()
    report = run_vm_fixture(rootfs=args.rootfs, kernel=args.kernel, source=source,
                            expected_source_sha256=args.source_sha256)
    destination = Path(os.environ.get("RUNNER_TEMP", tempfile.gettempdir())) / "jarvis-vm-guest-proof.json"
    destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("QEMU TCG guest proof:", report["status"], report["source_sha256"])
    print("External user repository execution: DENIED")
    print("Receipt:", destination)


if __name__ == "__main__":
    main()
