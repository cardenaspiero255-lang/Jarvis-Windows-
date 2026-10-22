"""Real Git linked-worktree staging + rollback on an authorized disposable repo.

These tests create genuine local repositories, never pull, push or execute
project code. Failure injections must restore exact HEAD/index/files/refs.
"""
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

from authorized_git_transaction import (
    AuthorizedGitTransaction, GitTransactionDenied, GitRollbackIncomplete,
)

ORIGINAL = b"def total(price, qty):\n    return price - qty\n"
PATCH = b"def total(price, qty):\n    return qty * price\n"


def git(cwd, *args):
    result = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                            check=True, timeout=15)
    return result.stdout.decode("utf-8", errors="replace").strip()


class GitTransactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "repo"
        self.root.mkdir()
        (self.root / "src").mkdir()
        (self.root / "src" / "calc.py").write_bytes(ORIGINAL)
        (self.root / "README.md").write_bytes(b"# fixture\n")
        git(self.root, "init", "-b", "main")
        git(self.root, "add", "--", "src/calc.py", "README.md")
        git(self.root, "-c", "user.name=Test",
            "-c", "user.email=test@example.invalid",
            "commit", "-m", "baseline")
        self.tx = AuthorizedGitTransaction()
        self.base = self.snapshot()

    def snapshot(self):
        return {
            "head": git(self.root, "rev-parse", "HEAD"),
            "symbolic": git(self.root, "symbolic-ref", "HEAD"),
            "status": git(self.root, "status", "--porcelain=v1", "--untracked-files=all"),
            "branches": git(self.root, "for-each-ref", "--format=%(refname) %(objectname)"),
            "worktrees": git(self.root, "worktree", "list", "--porcelain"),
            "index": hashlib.sha256((self.root / ".git" / "index").read_bytes()).hexdigest(),
            "files": {(self.root / p).read_bytes() for p in ("README.md", "src/calc.py")},
        }

    def stage(self, **override):
        params = {
            "repo_root": self.root, "path": "src/calc.py",
            "original_sha256": hashlib.sha256(ORIGINAL).hexdigest(),
            "patched_bytes": PATCH,
            "patched_sha256": hashlib.sha256(PATCH).hexdigest(),
            "approved": True, "owner": "desktop-owner",
        }
        params.update(override)
        return self.tx.stage(**params)

    def test_stages_exact_patch_on_real_branch_without_touching_original_checkout(self):
        receipt = self.stage()
        self.assertEqual(receipt["status"], "staged_local_git_branch")
        self.assertEqual(receipt["source_sha256"], hashlib.sha256(PATCH).hexdigest())
        self.assertFalse(receipt["published"])
        self.assertFalse(receipt["tests_executed"])
        self.assertEqual((self.root / "src" / "calc.py").read_bytes(), ORIGINAL)
        self.assertEqual(git(self.root, "rev-parse", "HEAD"), self.base["head"])
        self.assertEqual(git(self.root, "symbolic-ref", "HEAD"), self.base["symbolic"])
        self.assertEqual(git(self.root, "status", "--porcelain=v1", "--untracked-files=all"), "")
        self.assertIn("jarvis/review-", receipt["branch"])
        self.assertIn(receipt["branch"], git(self.root, "branch", "--list"))
        self.assertEqual((Path(receipt["worktree"]) / "src" / "calc.py").read_bytes(), PATCH)
        backup = Path(receipt["backup_path"])
        self.assertTrue(backup.is_file())
        with zipfile.ZipFile(backup) as z:
            self.assertEqual(z.read("files/src/calc.py"), ORIGINAL)
            self.assertEqual(z.read("files/README.md"), b"# fixture\n")
            self.assertIn("manifest.json", z.namelist())
        self.assertNotIn("push", receipt)
        self.tx.rollback(receipt["transaction_id"], owner="desktop-owner")
        self.assertEqual(self.snapshot(), self.base)
        self.assertFalse(backup.exists())

    def test_failures_after_worktree_branch_write_or_verify_restore_exact_snapshot(self):
        for failure_point in ("after_worktree", "after_branch", "after_patch", "after_verify"):
            with self.subTest(failure_point=failure_point):
                with self.assertRaises(GitTransactionDenied):
                    self.stage(inject_failure=failure_point)
                self.assertEqual(self.snapshot(), self.base)

    def test_rejects_unapproved_wrong_digest_and_outside_path_without_changes(self):
        for overrides in (
            {"approved": False},
            {"approved": "true"},
            {"original_sha256": "0" * 64},
            {"patched_sha256": "0" * 64},
            {"path": "../calc.py"},
            {"path": ".git/config"},
            {"path": "README.md"},
        ):
            with self.subTest(overrides=str(overrides)):
                with self.assertRaises(GitTransactionDenied):
                    self.stage(**overrides)
                self.assertEqual(self.snapshot(), self.base)

    def test_dirty_or_untracked_repo_is_rejected(self):
        (self.root / "dirty.txt").write_text("untracked")
        with self.assertRaises(GitTransactionDenied):
            self.stage()
        (self.root / "dirty.txt").unlink()
        (self.root / "src" / "calc.py").write_bytes(PATCH)
        with self.assertRaises(GitTransactionDenied):
            self.stage()
        (self.root / "src" / "calc.py").write_bytes(ORIGINAL)
        # Ordinary Git status can refresh index stat-cache metadata after a
        # deliberate external edit; compare logical index instead of raw bytes.
        restored = self.snapshot()
        baseline = dict(self.base)
        restored.pop("index")
        baseline.pop("index")
        self.assertEqual(restored, baseline)

    def test_exact_owner_and_session_required_to_rollback(self):
        receipt = self.stage()
        with self.assertRaises(GitTransactionDenied):
            self.tx.rollback(receipt["transaction_id"], owner="wrong-owner")
        self.assertTrue(Path(receipt["worktree"]).exists())
        self.tx.rollback(receipt["transaction_id"], owner="desktop-owner")
        with self.assertRaises(GitTransactionDenied):
            self.tx.rollback(receipt["transaction_id"], owner="desktop-owner")
        self.assertEqual(self.snapshot(), self.base)

    def test_refuses_symlinks_and_repo_managed_filter_config(self):
        attr = self.root / ".gitattributes"
        attr.write_text("*.py filter=evil\n")
        git(self.root, "add", "--", ".gitattributes")
        git(self.root, "-c", "user.name=Test", "-c",
            "user.email=test@example.invalid", "commit", "-m", "attributes")
        snapshot = self.snapshot()
        with self.assertRaises(GitTransactionDenied):
            self.stage()
        self.assertEqual(self.snapshot(), snapshot)

    def test_rollback_detects_interference_and_preserves_recovery(self):
        receipt = self.stage()
        # Simulate someone editing the staged worktree after approval:
        (Path(receipt["worktree"]) / "src" / "calc.py").write_bytes(b"external change\n")
        with self.assertRaises(GitRollbackIncomplete):
            self.tx.rollback(receipt["transaction_id"], owner="desktop-owner")
        self.assertTrue(Path(receipt["backup_path"]).exists())
        self.assertEqual((self.root / "src" / "calc.py").read_bytes(), ORIGINAL)
        self.assertEqual(git(self.root, "rev-parse", "HEAD"), self.base["head"])


if __name__ == "__main__":
    unittest.main()
