"""Recovery after a process dies mid-Git transaction; no project code executed."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from authorized_git_transaction import (
    AuthorizedGitTransaction, GitRollbackIncomplete, GitTransactionDenied,
)

ORIGINAL = b"def total(price, qty):\n    return price - qty\n"
PATCHED = b"def total(price, qty):\n    return qty * price\n"


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


class DurableGitRecoveryTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.home = Path(t.name)
        self.repo = self.home / "project"
        self.repo.mkdir()
        (self.repo / "src").mkdir()
        (self.repo / "src/calc.py").write_bytes(ORIGINAL)
        (self.repo / "README.md").write_bytes(b"fixture\n")
        git(self.repo, "init", "-b", "main")
        git(self.repo, "add", "--", "src/calc.py", "README.md")
        git(self.repo, "-c", "user.name=Fixture", "-c",
            "user.email=fixture@example.invalid", "commit", "-m", "base")
        self.recovery = self.home / "recovery-store"
        self.head = git(self.repo, "rev-parse", "HEAD")
        self.before = self.snapshot()

    def snapshot(self):
        return {
            "head": git(self.repo, "rev-parse", "HEAD"),
            "ref": git(self.repo, "symbolic-ref", "HEAD"),
            "refs": git(self.repo, "for-each-ref", "--format=%(refname) %(objectname)"),
            "worktrees": git(self.repo, "worktree", "list", "--porcelain"),
            "status": git(self.repo, "status", "--porcelain", "--untracked-files=all"),
            "index": hashlib.sha256((self.repo / ".git/index").read_bytes()).hexdigest(),
            "file": (self.repo / "src/calc.py").read_bytes(),
        }

    def stage(self):
        controller = AuthorizedGitTransaction(recovery_root=self.recovery)
        receipt = controller.stage(
            repo_root=self.repo, path="src/calc.py",
            original_sha256=hashlib.sha256(ORIGINAL).hexdigest(),
            patched_bytes=PATCHED, patched_sha256=hashlib.sha256(PATCHED).hexdigest(),
            owner="desktop-owner", approved=True,
        )
        return receipt

    def test_staged_branch_can_be_recovered_by_new_controller(self):
        r = self.stage()
        self.assertTrue((self.recovery / r["transaction_id"] / "journal.json").is_file())
        self.assertTrue(Path(r["backup_path"]).is_file())
        self.assertEqual((self.repo / "src/calc.py").read_bytes(), ORIGINAL)
        fresh = AuthorizedGitTransaction(recovery_root=self.recovery)
        outcomes = fresh.recover_pending()
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0]["status"], "recovered")
        self.assertEqual(self.snapshot(), self.before)
        self.assertFalse(Path(r["backup_path"]).exists())
        self.assertEqual(fresh.recover_pending(), [])

    def test_hard_crash_at_each_phase_then_restart_restores_exact_snapshot(self):
        for point in ("after_backup", "after_worktree", "after_branch",
                      "after_patch", "after_staged"):
            with self.subTest(point=point):
                # Run real Git in another Python interpreter and kill it without
                # finally/atexit, to prove restart does not need process memory.
                script = (
                    "import os, pathlib\n"
                    "import authorized_git_transaction as m\n"
                    "def crash(at):\n"
                    "    if at == "+repr(point)+": os._exit(47)\n"
                    "m._crash_test_checkpoint = crash\n"
                    "m.AuthorizedGitTransaction(recovery_root=pathlib.Path("+repr(str(self.recovery))+")).stage("
                    "repo_root=pathlib.Path("+repr(str(self.repo))+"),"
                    "path='src/calc.py',original_sha256="+repr(hashlib.sha256(ORIGINAL).hexdigest())+","
                    "patched_bytes="+repr(PATCHED)+","
                    "patched_sha256="+repr(hashlib.sha256(PATCHED).hexdigest())+","
                    "owner='desktop-owner',approved=True)\n"
                )
                child = subprocess.run([sys.executable, "-c", script],
                                       cwd=str(Path(__file__).parent),
                                       capture_output=True, timeout=40)
                self.assertEqual(child.returncode, 47,
                                 child.stderr.decode(errors="replace"))
                outcomes = AuthorizedGitTransaction(
                    recovery_root=self.recovery).recover_pending()
                self.assertEqual([o["status"] for o in outcomes], ["recovered"])
                self.assertEqual(self.snapshot(), self.before)
                self.assertEqual(list(self.recovery.glob("*/journal.json")), [])

    def test_hard_crash_while_rolling_back_is_idempotently_resumed(self):
        for phase in ("after_worktree_removed", "after_branch_removed"):
            with self.subTest(phase=phase):
                receipt = self.stage()
                script = (
                    "import os,pathlib\n"
                    "import durable_git_recovery as m\n"
                    "def crash(at):\n"
                    "    if at == " + repr(phase) + ": os._exit(48)\n"
                    "m._recovery_crash_checkpoint = crash\n"
                    "m.recover_pending(pathlib.Path(" + repr(str(self.recovery)) + "))\n"
                )
                result = subprocess.run([sys.executable, "-c", script],
                                        cwd=str(Path(__file__).parent),
                                        capture_output=True, timeout=40)
                self.assertEqual(result.returncode, 48,
                                 result.stderr.decode(errors="replace"))
                self.assertTrue(Path(receipt["backup_path"]).is_file())
                outcomes = AuthorizedGitTransaction(
                    recovery_root=self.recovery).recover_pending()
                self.assertEqual([o["status"] for o in outcomes], ["recovered"])
                self.assertEqual(self.snapshot(), self.before)

    def test_interference_blocks_destructive_cleanup_and_keeps_recovery_zip(self):
        r = self.stage()
        (Path(r["worktree"]) / "src/calc.py").write_bytes(b"external change\n")
        fresh = AuthorizedGitTransaction(recovery_root=self.recovery)
        results = fresh.recover_pending()
        self.assertEqual(results[0]["status"], "blocked")
        self.assertTrue(Path(r["backup_path"]).exists())
        self.assertTrue(Path(r["worktree"]).exists())
        self.assertEqual((self.repo / "src/calc.py").read_bytes(), ORIGINAL)

    def test_corrupted_backup_refuses_recovery_and_preserves_diagnostics(self):
        r = self.stage()
        Path(r["backup_path"]).write_bytes(b"tampered")
        status = AuthorizedGitTransaction(recovery_root=self.recovery).recover_pending()
        self.assertEqual(status[0]["status"], "blocked")
        self.assertEqual((self.repo / "src/calc.py").read_bytes(), ORIGINAL)
        self.assertTrue(Path(r["backup_path"]).is_file())

    def test_outside_path_or_symlinked_journal_cannot_trigger_git_operations(self):
        self.recovery.mkdir()
        malicious = self.recovery / ("a" * 32)
        malicious.mkdir()
        (malicious / "journal.json").write_text(
            json.dumps({"repository": str(self.repo), "branch": "main",
                        "worktree": str(self.repo), "phase": "staged"}))
        checker = AuthorizedGitTransaction(recovery_root=self.recovery)
        status = checker.recover_pending()
        self.assertEqual(status[0]["status"], "blocked")
        self.assertEqual(self.snapshot(), self.before)
        self.assertTrue(malicious.exists())
        if hasattr(os, "symlink"):
            other = self.home / "external"
            other.mkdir()
            try:
                (self.recovery / "badlink").symlink_to(other, target_is_directory=True)
            except OSError:
                return
            checker.recover_pending()
            self.assertTrue(other.exists())
            self.assertEqual(self.snapshot(), self.before)

    def test_journal_keeps_no_source_data_or_owner_secret(self):
        r = self.stage()
        journal = (self.recovery / r["transaction_id"] / "journal.json").read_text()
        self.assertNotIn("desktop-owner", journal)
        self.assertNotIn("return qty * price", journal)
        self.assertEqual(self.snapshot()["file"], ORIGINAL)


if __name__ == "__main__":
    unittest.main()
