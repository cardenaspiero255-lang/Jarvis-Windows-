"""Disposable Windows Hyper-V guest fixture (no real user repository allowed).

Stages an approved fixed arithmetic patch in a NEW local Git worktree, pauses
AFTER a durable journal or patch fsync, then the host MUST turn off virtual
power via Hyper-V Stop-VM -TurnOff. On next boot, independently recover and
verify the entire HEAD/index/files/refs/worktree snapshot.

Test protocol only. Does not execute patched source, publish, or access remote.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

import authorized_git_transaction as transaction

ORIGINAL = b"def total(price, qty):\n    return price - qty\n"
PATCHED = b"def total(price, qty):\n    return qty * price\n"
PHASES = ("after_backup", "after_worktree", "after_branch",
          "after_patch", "after_staged")


def _git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root,
                                   text=True, timeout=15).strip()


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _location(value):
    root = Path(value).resolve()
    if not root.name.startswith("JARVIS-POWERLAB-") or len(root.name) > 96:
        raise ValueError("Only explicitly disposable guest fixture directories allowed")
    return root


def _snapshot(repo):
    return {
        "head": _git(repo, "rev-parse", "HEAD"),
        "symbolic": _git(repo, "symbolic-ref", "HEAD"),
        "refs": _git(repo, "for-each-ref", "--format=%(refname) %(objectname)"),
        "worktrees": _git(repo, "worktree", "list", "--porcelain"),
        "status": _git(repo, "status", "--porcelain=v1", "--untracked-files=all"),
        "index_sha256": _hash((repo / ".git/index").read_bytes()),
        "target_sha256": _hash((repo / "src/calc.py").read_bytes()),
        "readme_sha256": _hash((repo / "README.md").read_bytes()),
    }


def initialize(workspace):
    repo = workspace / "authorized-fixture"
    if repo.exists() or (workspace / "baseline.json").exists():
        raise ValueError("Cannot overwrite an existing disposable guest workspace")
    repo.mkdir(parents=True)
    (repo / "src").mkdir()
    (repo / "src/calc.py").write_bytes(ORIGINAL)
    (repo / "README.md").write_bytes(b"# Disposable JARVIS fixture\n")
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, timeout=20)
    subprocess.run(["git", "add", "--", "src/calc.py", "README.md"],
                   cwd=repo, check=True, timeout=20)
    subprocess.run(["git", "-c", "user.name=JarvisPowerLab",
                    "-c", "user.email=fixture@example.invalid",
                    "commit", "-m", "trusted fixture"],
                   cwd=repo, check=True, timeout=20)
    snapshot = _snapshot(repo)
    (workspace / "baseline.json").write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    print("POWERLAB_INITIALIZED", _hash(json.dumps(snapshot, sort_keys=True).encode()), flush=True)


def stage_and_wait(workspace, phase):
    if phase not in PHASES:
        raise ValueError("Unrecognized guest test phase")
    marker = workspace / "ready-for-virtual-power-off.json"
    if marker.exists():
        raise ValueError("Stale power-off marker detected")
    repo = workspace / "authorized-fixture"

    def checkpoint(at):
        if at != phase:
            return
        marker.write_text(json.dumps({
            "phase": phase, "type": "virtual_power_off_required",
            "baseline_sha256": _hash((workspace / "baseline.json").read_bytes()),
        }), encoding="utf-8")
        with marker.open("r+b") as file:
            file.flush()
            os.fsync(file.fileno())
        print("READY_FOR_HYPERV_TURNOFF", flush=True)
        while True:
            time.sleep(0.25)  # host MUST power off the VM, never resume this process

    transaction._crash_test_checkpoint = checkpoint
    transaction.AuthorizedGitTransaction(
        recovery_root=workspace / "recovery").stage(
        repo_root=repo, path="src/calc.py",
        original_sha256=_hash(ORIGINAL), patched_bytes=PATCHED,
        patched_sha256=_hash(PATCHED),
        approved=True, owner="only-disposable-powerlab",
    )
    raise RuntimeError("Fixture unexpectedly escaped its virtual power-cut checkpoint")


def verify_recovered(workspace):
    repo = workspace / "authorized-fixture"
    baseline = json.loads((workspace / "baseline.json").read_text(encoding="utf-8"))
    marker = json.loads((workspace / "ready-for-virtual-power-off.json").read_text(encoding="utf-8"))
    if marker.get("type") != "virtual_power_off_required":
        raise RuntimeError("No positive pre-powercut marker")
    result = transaction.AuthorizedGitTransaction(
        recovery_root=workspace / "recovery").recover_pending()
    if len(result) != 1 or result[0].get("status") != "recovered":
        raise RuntimeError("Guest recovery incomplete; preserve all evidence")
    actual = _snapshot(repo)
    if actual != baseline:
        raise RuntimeError("Git snapshot differs after virtual power restoration")
    proof = {
        "status": "virtual_powercut_guest_recovered",
        "phase": marker["phase"],
        "exact_original_git_snapshot_restored": True,
        "original_head": baseline["head"],
        "baseline_sha256": _hash(json.dumps(baseline, sort_keys=True).encode()),
        "physical_mains_power_cut": False,
        "real_windows_virtual_guest": True,
        "no_external_repositories_executed": True,
    }
    (workspace / "guest-proof.json").write_text(json.dumps(proof, indent=2), encoding="utf-8")
    print(json.dumps(proof), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("init", "stage", "recover"))
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--phase", choices=PHASES)
    args = parser.parse_args()
    workspace = _location(args.workspace)
    if args.action == "init":
        workspace.mkdir(parents=True, exist_ok=False)
        initialize(workspace)
    elif args.action == "stage":
        if not args.phase:
            parser.error("--phase is required for stage")
        stage_and_wait(workspace, args.phase)
    else:
        verify_recovered(workspace)


if __name__ == "__main__":
    main()
