"""Restart-safe journal and conservative recovery for authorized Git staging.

Only snapshots created by JARVIS within a private recovery directory are
considered. A journal is written and synced BEFORE any Git worktree mutation.
At startup, a controller reconstructs baseline source from a verified recovery
ZIP, checks the original tree and exact intended branch/worktree state, and
removes *only* the verified JARVIS temporary branch and linked worktree.

This is best-effort filesystem durability, not proof of surviving every
power loss, disk/controller cache, filesystem or kernel failure.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
import zipfile


class RecoveryBlocked(RuntimeError):
    pass


_TRANSACTION_ID = re.compile(r"^[A-Za-z0-9_-]{24,64}$")
_BRANCH = re.compile(r"^jarvis/review-[0-9a-f]{16}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def recovery_root(configured=None):
    """Persistent user-scoped directory; never auto-delete it with system temp."""
    if configured is None:
        if os.name == "nt":
            base = os.environ.get("LOCALAPPDATA")
            if not base:
                base = str(Path.home() / "AppData" / "Local")
            configured = Path(base) / "JARVIS" / "git-recovery"
        else:
            configured = Path.home() / ".local" / "state" / "jarvis" / "git-recovery"
    location = Path(configured).expanduser()
    # No symlink in the directory itself or an existing component.
    for parent in (location, *location.parents):
        if parent.is_symlink():
            raise RecoveryBlocked("Recovery store contains a symbolic link")
    location.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not location.is_dir() or location.is_symlink():
        raise RecoveryBlocked("Invalid recovery directory")
    return location.resolve(strict=True)


def _sync_dir(folder):
    if os.name != "nt":
        fd = os.open(str(folder), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def sync_file(path):
    with Path(path).open("rb") as file:
        os.fsync(file.fileno())
    _sync_dir(Path(path).parent)


def _serialize(data):
    return json.dumps(data, separators=(",", ":"), sort_keys=True,
                      ensure_ascii=True).encode("ascii")


def write_journal(folder, info):
    """Atomic replace + explicit flush, prior to worktree ref mutation."""
    folder = Path(folder)
    data = {**info, "format": "jarvis-git-recovery-v1"}
    data["checksum"] = _sha(_serialize(data))
    content = _serialize(data)
    if len(content) > 16384:
        raise RecoveryBlocked("Journal exceeds size bound")
    with tempfile.NamedTemporaryFile(mode="wb", dir=folder, prefix="journal-",
                                     suffix=".tmp", delete=False) as fh:
        tmp = Path(fh.name)
        try:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
    os.replace(tmp, folder / "journal.json")
    _sync_dir(folder)


def _journal(folder):
    directory = Path(folder)
    if not _TRANSACTION_ID.fullmatch(directory.name):
        raise RecoveryBlocked("Unknown recovery entry ID")
    file = directory / "journal.json"
    if directory.is_symlink() or not directory.is_dir() or file.is_symlink():
        raise RecoveryBlocked("Recovery journal is not a regular local file")
    try:
        if file.stat().st_size > 16384 or file.stat().st_size < 100:
            raise RecoveryBlocked("Journal missing or exceeds cap")
        data = json.loads(file.read_bytes())
    except (OSError, ValueError) as exc:
        raise RecoveryBlocked("Invalid recovery journal") from exc
    if not isinstance(data, dict) or data.get("format") != "jarvis-git-recovery-v1":
        raise RecoveryBlocked("Unrecognized recovery journal schema")
    checksum = data.pop("checksum", None)
    if not isinstance(checksum, str) or checksum != _sha(_serialize(data)):
        raise RecoveryBlocked("Journal digest mismatch")
    if (data.get("transaction_id") != directory.name
            or not _BRANCH.fullmatch(data.get("branch", ""))
            or not _SHA.fullmatch(data.get("backup_sha256", ""))
            or not _SHA.fullmatch(data.get("patched_sha256", ""))
            or not _SHA.fullmatch(data.get("original_sha256", ""))):
        raise RecoveryBlocked("Invalid recovery journal identity or digests")
    return data


def _load_backup(folder, journal):
    path = folder / "recovery.zip"
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
        raise RecoveryBlocked("Trusted recovery ZIP unavailable")
    if _sha(path.read_bytes()) != journal["backup_sha256"]:
        raise RecoveryBlocked("Recovery ZIP checksum mismatch")
    try:
        with zipfile.ZipFile(path, "r") as archive:
            manifest = json.loads(archive.read("manifest.json"))
            files = {}
            for filename, checksum in manifest["sha256"].items():
                if (not isinstance(filename, str) or len(filename) > 240
                        or filename.startswith(".") or ".." in filename.split("/")
                        or "\\" in filename or filename.startswith("/")
                        or ":" in filename or not _SHA.fullmatch(checksum)):
                    raise RecoveryBlocked("Unsafe file in recovery manifest")
                raw = archive.read("files/" + filename)
                if len(raw) > 128 * 1024 or _sha(raw) != checksum:
                    raise RecoveryBlocked("Recovery file checksum mismatch")
                files[filename] = raw
            if len(files) > 40 or sum(map(len, files.values())) > 2 * 1024 * 1024:
                raise RecoveryBlocked("Unbounded recovery snapshot")
            if _sha(archive.read("git-index.bin")) != manifest["index_sha256"]:
                raise RecoveryBlocked("Recovery Git index differs")
    except (OSError, ValueError, KeyError, RuntimeError, zipfile.BadZipFile,
            UnicodeError) as exc:
        raise RecoveryBlocked("Invalid recovery package") from exc
    if not files or journal.get("path") not in files:
        raise RecoveryBlocked("Reviewed source absent from backup")
    if _sha(files[journal["path"]]) != journal["original_sha256"]:
        raise RecoveryBlocked("Original source digest mismatch")
    if not isinstance(journal.get("baseline"), dict):
        raise RecoveryBlocked("Missing Git baseline")
    baseline = journal["baseline"]
    required = ("head", "symbolic", "refs", "worktrees", "index_sha256")
    if any(manifest.get(key) != baseline.get(key) for key in required):
        raise RecoveryBlocked("Journal does not match backup baseline")
    return files, baseline


def _worktree_blocks(text):
    return [part.strip() for part in text.split("\n\n") if part.strip()]


def recover_entry(folder):
    """Verify first, remove temporary refs/worktree second; never reset main."""
    from authorized_git_transaction import (
        _git, _inventory, _baseline, GitTransactionDenied
    )
    directory = Path(folder)
    journal = _journal(directory)
    files, baseline = _load_backup(directory, journal)
    try:
        root = Path(journal["repository"]).resolve(strict=True)
        expected_worktree = (directory / "worktree").resolve()
    except (TypeError, OSError, ValueError) as exc:
        raise RecoveryBlocked("Repository or worktree missing") from exc
    if (not root.is_dir() or not (root / ".git").is_dir()
            or (root / ".git").is_symlink()
            or journal.get("worktree") != str(directory / "worktree")
            or not root.is_absolute()
            or expected_worktree != directory.resolve() / "worktree"):
        raise RecoveryBlocked("Recovery journal attempts path redirection")
    target_path = journal["path"]
    if (not isinstance(target_path, str)
            or not target_path.endswith(".py")
            or target_path.startswith(".")
            or "\\" in target_path or ".." in target_path.split("/")):
        raise RecoveryBlocked("Unsafe reviewed Git target")
    target = root.joinpath(*PurePosixPath(target_path).parts)
    if target.is_symlink() or not target.is_file():
        raise RecoveryBlocked("Original target is not a regular file")
    # No modifications to the original checkout are permitted, ever.
    if (_git(root, "rev-parse", "HEAD") != baseline["head"]
            or _git(root, "symbolic-ref", "HEAD") != baseline["symbolic"]
            or _git(root, "status", "--porcelain=v1", "--untracked-files=all")
            or _sha((root / ".git/index").read_bytes()) != baseline["index_sha256"]
            or _inventory(root) != files):
        raise RecoveryBlocked("Original checkout changed; recovery cannot delete artifacts")
    original_refs = set(baseline["refs"].splitlines())
    new_ref = "refs/heads/" + journal["branch"] + " " + baseline["head"]
    current_refs = set(_git(root, "for-each-ref",
                            "--format=%(refname) %(objectname)").splitlines())
    if current_refs not in (original_refs, original_refs | {new_ref}):
        raise RecoveryBlocked("Unexpected Git refs since snapshot")
    branch_exists = new_ref in current_refs
    original_worktrees = set(_worktree_blocks(baseline["worktrees"]))
    current_worktrees = set(_worktree_blocks(_git(root, "worktree", "list", "--porcelain")))
    additional = current_worktrees - original_worktrees
    if not original_worktrees.issubset(current_worktrees) or len(additional) > 1:
        raise RecoveryBlocked("Unexpected linked worktree topology")
    worktree_listed = False
    for block in additional:
        parts = block.splitlines()
        if (not parts or parts[0] != "worktree " + str(directory / "worktree")
                and Path(parts[0][9:]).resolve() != expected_worktree):
            raise RecoveryBlocked("Unrecognized linked worktree")
        if ("HEAD " + baseline["head"] not in parts
                or not (("branch refs/heads/" + journal["branch"]) in parts
                        or "detached" in parts)):
            raise RecoveryBlocked("Linked worktree moved to a different commit")
        worktree_listed = True
    if expected_worktree.exists() and not worktree_listed:
        raise RecoveryBlocked("Unregistered worktree directory; do not delete")
    if worktree_listed:
        if not expected_worktree.is_dir() or expected_worktree.is_symlink():
            raise RecoveryBlocked("Linked worktree missing or symlinked")
        staged_target = expected_worktree.joinpath(*PurePosixPath(target_path).parts)
        if staged_target.is_symlink() or not staged_target.is_file():
            raise RecoveryBlocked("Staged source changed or missing")
        staged_digest = _sha(staged_target.read_bytes())
        if staged_digest not in (journal["original_sha256"], journal["patched_sha256"]):
            raise RecoveryBlocked("Staged bytes changed by another actor")
        changed = _git(expected_worktree, "status", "--porcelain=v1",
                       "--untracked-files=all")
        if changed and changed != "M " + target_path:
            raise RecoveryBlocked("Unexpected worktree status; preserve recovery")
        if (_git(expected_worktree, "rev-parse", "HEAD") != baseline["head"]
                or _git(expected_worktree, "diff", "--name-only") not in ("", target_path)):
            raise RecoveryBlocked("Linked worktree HEAD or diff changed")
        _git(root, "worktree", "remove", "--force", str(expected_worktree))
    if branch_exists:
        _git(root, "branch", "-D", journal["branch"])
    if _baseline(root) != baseline or _inventory(root) != files:
        raise RecoveryBlocked("Recovery did not restore exact Git snapshot")
    shutil.rmtree(directory)
    return {"status": "recovered", "transaction_id": directory.name,
            "restored_exact_snapshot": True, "published": False}


def recover_pending(store):
    """All entries independent: corruption cannot block unrelated recoveries."""
    root = recovery_root(store)
    results = []
    for entry in sorted(root.iterdir(), key=lambda p: p.name):
        if entry.is_symlink() or not entry.is_dir():
            results.append({"status": "blocked", "transaction_id": entry.name})
            continue
        try:
            results.append(recover_entry(entry))
        except (RecoveryBlocked, OSError, ValueError, KeyError, RuntimeError):
            results.append({"status": "blocked", "transaction_id": entry.name})
    return results
