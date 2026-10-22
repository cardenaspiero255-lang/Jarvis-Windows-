"""Authorized Git branch staging with exact snapshot and conservative rollback.

The ONLY mutations to the authorized repository are new refs + linked-worktree
metadata; the original checkout, index, HEAD and source files remain untouched.
External code/tests/hooks/filters are NEVER executed. No Git clone/fetch/push,
merge, commit or shell commands. The user explicitly names the Git root and
approves exact original and proposed SHA-256 digests. A private recovery ZIP is
saved OUTSIDE the project BEFORE any Git metadata mutation.

This is for an authorized, clean, bounded, conventional local Git repo, NOT an
executor of potentially malicious repositories or a certified crash-safe DB.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import subprocess
import tempfile
import zipfile
from durable_git_recovery import (
    recovery_root as _recovery_root, write_journal, sync_file,
    recover_entry, recover_pending as _recover_pending,
)


def _crash_test_checkpoint(_phase):
    """No-op; subprocess regression injects os._exit at crash boundaries."""
    return None


class GitTransactionDenied(ValueError):
    pass


class GitRollbackIncomplete(RuntimeError):
    """Keep recovery backup intact if unexpected edits make rollback unsafe."""


_SHA = re.compile(r"^[0-9a-f]{64}$")
_MAX_TRACKED = 40
_MAX_TOTAL_BYTES = 2 * 1024 * 1024
_MAX_FILE = 128 * 1024
_ALLOWED_EXTENSIONS = {".py", ".md", ".json", ".js", ".jsx", ".ts", ".tsx", ".kt", ".kts"}
_FORBIDDEN = {".gitattributes", ".gitmodules", ".lfsconfig", ".git"}
_FAILURE_POINTS = {"after_worktree", "after_branch", "after_patch", "after_verify"}


def _sha(blob):
    return hashlib.sha256(blob).hexdigest()


def _git(root, *args):
    """Constrained, no-shell local Git; ignores inherited Git controls and hooks."""
    allowed = ("PATH", "SystemRoot", "SYSTEMROOT", "WINDIR",
               "COMSPEC", "PATHEXT", "TEMP", "TMP", "LANG", "LC_ALL")
    env = {name: os.environ[name] for name in allowed if name in os.environ}
    env.update({
        "HOME": str(root), "USERPROFILE": str(root),
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0", "GIT_LFS_SKIP_SMUDGE": "1",
        "GIT_PROTOCOL_FROM_USER": "0",
    })
    argv = [
        "git", "-c", "core.hooksPath=" + str(root / ".jarvis-disabled-hooks"),
        "-c", "core.fsmonitor=false", "-c", "core.autocrlf=false",
        "-c", "core.attributesFile=" + str(root / ".jarvis-no-attributes"),
        "-c", "commit.gpgsign=false",
        *args,
    ]
    try:
        result = subprocess.run(argv, cwd=str(root), env=env, shell=False,
                                capture_output=True, timeout=20, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        raise GitTransactionDenied("Restricted Git operation failed") from exc
    try:
        return result.stdout.decode("utf-8", "strict").strip()
    except UnicodeDecodeError as exc:
        raise GitTransactionDenied("Git emitted unsupported filename encoding") from exc


def _validate_path(root, path):
    if not isinstance(path, str) or not 1 <= len(path) <= 200 or "\\" in path:
        raise GitTransactionDenied("Invalid target path")
    parts = PurePosixPath(path).parts
    if (path.startswith("/") or ":" in path or "\x00" in path
            or not parts or any(p in (".", "..") or p.startswith(".") for p in parts)
            or PurePosixPath(path).as_posix() != path
            or PurePosixPath(path).suffix != ".py"):
        raise GitTransactionDenied("Only a specific tracked Python source path is allowed")
    target = root.joinpath(*parts)
    for n in range(1, len(parts) + 1):
        if root.joinpath(*parts[:n]).is_symlink():
            raise GitTransactionDenied("Symlink target or ancestor forbidden")
    if not target.is_file() or not target.resolve(strict=True).is_relative_to(root):
        raise GitTransactionDenied("Target is not a regular in-repo file")
    return target


def _inventory(root):
    """Reject nonregular entries and costly or Git-configured source trees."""
    listing = _git(root, "ls-files", "--stage", "-z")
    entries = listing.split("\x00")
    if entries and entries[-1] == "":
        entries.pop()
    if not entries or len(entries) > _MAX_TRACKED:
        raise GitTransactionDenied("Repository tracked-file count exceeds cap")
    paths = {}
    total = 0
    for item in entries:
        if "\t" not in item:
            raise GitTransactionDenied("Malformed Git index listing")
        meta, name = item.split("\t", 1)
        mode = meta.split(" ", 1)[0]
        if mode not in ("100644", "100755"):
            raise GitTransactionDenied("Symlink, submodule or nonregular Git entry")
        components = name.split("/")
        if (not name or len(name) > 240 or any(
                not p or p in (".", "..") or p in _FORBIDDEN
                or p.startswith(".") and p != ".gitignore"
                for p in components)
                or name.startswith("/") or "\\" in name or ":" in name):
            raise GitTransactionDenied("Unsafe or Git-configured tracked pathname")
        if PurePosixPath(name).suffix.lower() not in _ALLOWED_EXTENSIONS and name != ".gitignore":
            raise GitTransactionDenied("Unsupported tracked file type")
        target = root.joinpath(*components)
        if not target.is_file() or target.is_symlink():
            raise GitTransactionDenied("Tracked file replaced with nonregular entry")
        for i in range(1, len(components)):
            if root.joinpath(*components[:i]).is_symlink():
                raise GitTransactionDenied("Tracked path has symlink ancestor")
        if not target.resolve(strict=True).is_relative_to(root):
            raise GitTransactionDenied("Tracked file escapes authorized root")
        data = target.read_bytes()
        if len(data) > _MAX_FILE:
            raise GitTransactionDenied("Tracked file too large")
        total += len(data)
        if total > _MAX_TOTAL_BYTES:
            raise GitTransactionDenied("Tracked data exceeds snapshot cap")
        paths[name] = data
    git_dir = root / ".git"
    if (git_dir / "info" / "attributes").exists() and (
            git_dir / "info" / "attributes").stat().st_size:
        raise GitTransactionDenied("Git info attributes may invoke custom filters")
    return paths


def _baseline(root):
    if _git(root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise GitTransactionDenied("Repository must have a clean index and working tree")
    head = _git(root, "rev-parse", "--verify", "HEAD")
    if not re.fullmatch(r"[0-9a-f]{40,64}", head):
        raise GitTransactionDenied("Invalid Git HEAD")
    return {
        "head": head,
        "symbolic": _git(root, "symbolic-ref", "HEAD"),
        "refs": _git(root, "for-each-ref", "--format=%(refname) %(objectname)"),
        "worktrees": _git(root, "worktree", "list", "--porcelain"),
        "index_sha256": _sha((root / ".git" / "index").read_bytes()),
    }


def _check_original(root, files, baseline):
    if _baseline(root) != baseline or _inventory(root) != files:
        raise GitTransactionDenied("Authorized repository changed after snapshot")


def _make_backup(root, base, files, destination):
    """Ensure a complete trusted recovery package exists before worktree add."""
    backup = destination / "recovery.zip"
    with zipfile.ZipFile(backup, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for path, blob in sorted(files.items()):
            z.writestr("files/" + path, blob)
        z.writestr("git-index.bin", (root / ".git" / "index").read_bytes())
        z.writestr("manifest.json", json.dumps({
            **base, "sha256": {path: _sha(blob) for path, blob in files.items()},
            "repository": str(root),
            "read_only_backup": True,
        }, sort_keys=True).encode("utf-8"))
    if hasattr(os, "chmod"):
        os.chmod(backup, 0o600)
    with zipfile.ZipFile(backup) as z:
        for path, blob in files.items():
            if z.read("files/" + path) != blob:
                raise GitTransactionDenied("Recovery ZIP failed its verification")
        if _sha(z.read("git-index.bin")) != base["index_sha256"]:
            raise GitTransactionDenied("Recovery index copy failed checksum")
    sync_file(backup)
    return backup


class AuthorizedGitTransaction:
    def __init__(self, *, recovery_root=None):
        self._live = {}
        self._store = _recovery_root(recovery_root)
        self._recovery_checked = False
        self._recovery_blocked = False

    def recover_pending(self):
        """On startup, restore interrupted branches using disk journal only."""
        result = _recover_pending(self._store)
        self._recovery_checked = True
        self._recovery_blocked = any(x["status"] != "recovered" for x in result)
        return result

    def stage(self, *, repo_root, path, original_sha256, patched_bytes,
              patched_sha256, approved=False, owner=None, inject_failure=None):
        if not self._recovery_checked:
            self.recover_pending()
        if self._recovery_blocked:
            raise GitTransactionDenied("Pending Git recovery blocked; refuse new staging")
        if (approved is not True or not isinstance(owner, str) or not owner
                or len(owner) > 256):
            raise GitTransactionDenied("Explicit approval and local owner are required")
        if (not isinstance(patched_bytes, bytes) or not patched_bytes
                or len(patched_bytes) > _MAX_FILE
                or not isinstance(original_sha256, str) or not _SHA.fullmatch(original_sha256)
                or not isinstance(patched_sha256, str) or not _SHA.fullmatch(patched_sha256)
                or not hmac.compare_digest(_sha(patched_bytes), patched_sha256)):
            raise GitTransactionDenied("Modified source does not match reviewed digest")
        if inject_failure is not None and inject_failure not in _FAILURE_POINTS:
            raise GitTransactionDenied("Invalid test failure point")
        try:
            repo = Path(repo_root).resolve(strict=True)
        except (OSError, ValueError, TypeError) as exc:
            raise GitTransactionDenied("Invalid authorized Git directory") from exc
        if (not repo.is_dir() or not (repo / ".git").is_dir()
                or (repo / ".git").is_symlink()
                or Path(_git(repo, "rev-parse", "--show-toplevel")).resolve()
                != repo):
            raise GitTransactionDenied("Only a real top-level Git working tree is supported")
        target = _validate_path(repo, path)
        files = _inventory(repo)
        if path not in files or not hmac.compare_digest(_sha(files[path]), original_sha256):
            raise GitTransactionDenied("Source file differs from the reviewed ZIP")
        if files[path] == patched_bytes:
            raise GitTransactionDenied("No material change")
        # Never execute patched source; its AST policy was checked by review.
        base = _baseline(repo)
        transaction_id = secrets.token_urlsafe(24)
        backup_parent = self._store / transaction_id
        try:
            backup_parent.mkdir(mode=0o700)
        except OSError as exc:
            raise GitTransactionDenied("Could not allocate persistent recovery slot") from exc
        worktree = backup_parent / "worktree"
        branch = "jarvis/review-" + secrets.token_hex(8)
        created_worktree = False
        branch_created = False
        try:
            backup = _make_backup(repo, base, files, backup_parent)
            _check_original(repo, files, base)
            # Must be durable *before* any refs or linked-worktree metadata exist.
            write_journal(backup_parent, {
                "transaction_id": transaction_id,
                "repository": str(repo), "worktree": str(worktree),
                "branch": branch, "path": path, "baseline": base,
                "original_sha256": original_sha256,
                "patched_sha256": patched_sha256,
                "backup_sha256": _sha(backup.read_bytes()),
            })
            _crash_test_checkpoint("after_backup")
            _git(repo, "worktree", "add", "--detach", str(worktree), base["head"])
            created_worktree = True
            _crash_test_checkpoint("after_worktree")
            if inject_failure == "after_worktree":
                raise GitTransactionDenied("Injected worktree failure")
            _git(worktree, "switch", "-c", branch)
            branch_created = True
            _crash_test_checkpoint("after_branch")
            if inject_failure == "after_branch":
                raise GitTransactionDenied("Injected branch failure")
            destination = worktree.joinpath(*PurePosixPath(path).parts)
            if destination.is_symlink() or not destination.is_file():
                raise GitTransactionDenied("Linked worktree path invalid")
            if not hmac.compare_digest(_sha(destination.read_bytes()), original_sha256):
                raise GitTransactionDenied("Linked checkout does not match approved source")
            with destination.open("wb") as staged:
                staged.write(patched_bytes)
                staged.flush()
                os.fsync(staged.fileno())
            _crash_test_checkpoint("after_patch")
            if inject_failure == "after_patch":
                raise GitTransactionDenied("Injected patch write failure")
            if (_sha(destination.read_bytes()) != patched_sha256
                    or _git(worktree, "diff", "--name-only") != path
                    or _git(worktree, "rev-parse", "HEAD") != base["head"]):
                raise GitTransactionDenied("Unexpected staged Git change")
            if inject_failure == "after_verify":
                raise GitTransactionDenied("Injected verification failure")
            # Snapshot the original after staging; only the newly added branch
            # and linked worktree are permitted to differ from baseline.
            if (_sha(target.read_bytes()) != original_sha256
                    or _git(repo, "status", "--porcelain=v1", "--untracked-files=all")
                    or _git(repo, "rev-parse", "HEAD") != base["head"]
                    or _git(repo, "symbolic-ref", "HEAD") != base["symbolic"]
                    or _sha((repo / ".git" / "index").read_bytes()) != base["index_sha256"]):
                raise GitTransactionDenied("Original checkout changed; refuse staging")
        except BaseException as exc:
            try:
                if (backup_parent / "journal.json").is_file():
                    recover_entry(backup_parent)
                else:
                    if created_worktree or branch_created:
                        raise GitRollbackIncomplete("Git changed before durable journal")
                    shutil.rmtree(backup_parent)
            except BaseException as rollback_error:
                raise GitRollbackIncomplete(
                    "Automatic rollback not certified; keep recovery ZIP at "
                    + str(backup_parent / "recovery.zip")) from rollback_error
            raise GitTransactionDenied("Staging failed; original Git snapshot restored") from exc
        _crash_test_checkpoint("after_staged")
        self._live[transaction_id] = {
            "owner": owner, "repo": repo, "worktree": worktree,
            "branch": branch, "baseline": base, "files": files,
            "backup": backup_parent, "path": path,
            "patched_sha256": patched_sha256,
        }
        return {
            "status": "staged_local_git_branch", "transaction_id": transaction_id,
            "branch": branch, "worktree": str(worktree),
            "backup_path": str(backup_parent / "recovery.zip"),
            "baseline_commit": base["head"],
            "original_sha256": original_sha256, "source_sha256": patched_sha256,
            "modified_files": [path], "published": False,
            "tests_executed": False, "original_checkout_modified": False,
            "rollback_available": True,
        }

    def rollback(self, transaction_id, *, owner):
        state = self._live.get(transaction_id)
        if (not isinstance(owner, str) or not isinstance(transaction_id, str)
                or state is None or not hmac.compare_digest(owner, state["owner"])):
            raise GitTransactionDenied("Unknown or unauthorized Git transaction")
        try:
            report = recover_entry(state["backup"])
        except BaseException as exc:
            raise GitRollbackIncomplete(
                "Cannot confirm exact restoration; persistent recovery ZIP preserved") from exc
        del self._live[transaction_id]
        return {
            "status": "git_rolled_back",
            "restored_head": state["baseline"]["head"],
            "restored_exact_snapshot": report["restored_exact_snapshot"],
            "published": False, "original_checkout_modified": False,
        }
