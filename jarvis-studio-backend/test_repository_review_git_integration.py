"""End-to-end approved external ZIP -> linked Git branch -> exact rollback."""
import hashlib
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

from repository_review_sessions import RepositoryReviewSessions, ReviewDenied


ORIGINAL = b"def total(price, qty):\n    return price - qty\n"
PATCH = b"def total(price, qty):\n    return qty * price\n"


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


class RepositoryReviewGitIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / "authorized"
        (self.repo / "src").mkdir(parents=True)
        (self.repo / "src/calc.py").write_bytes(ORIGINAL)
        (self.repo / "README.md").write_bytes(b"# fixture\n")
        git(self.repo, "init", "-b", "main")
        git(self.repo, "add", "--", "src/calc.py", "README.md")
        git(self.repo, "-c", "user.name=Fixture",
            "-c", "user.email=fixture@example.invalid", "commit", "-m", "initial")
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("src/calc.py", ORIGINAL)
            z.writestr("README.md", b"# fixture\n")
        self.svc = RepositoryReviewSessions()
        from authorized_git_transaction import AuthorizedGitTransaction
        self.svc._git = AuthorizedGitTransaction(recovery_root=Path(self.temp.name) / 'recovery')
        self.owner = "local-window"
        self.sid = self.svc.inspect(self.owner, archive.getvalue())["session_id"]
        self.preview = self.svc.propose(self.owner, self.sid, "src/calc.py", "total",
                                        propose=lambda *_:
                                        '{"replacement":"return qty * price"}')
        self.svc.apply_copy(self.owner, self.sid,
                            self.preview["patched_sha256"], approved=True)
        self.head = git(self.repo, "rev-parse", "HEAD")

    def test_review_to_authorized_branch_and_restore(self):
        receipt = self.svc.stage_git(
            self.owner, self.sid, str(self.repo),
            self.preview["patched_sha256"], approved=True)
        self.assertEqual(receipt["status"], "git_branch_staged")
        self.assertEqual((self.repo / "src/calc.py").read_bytes(), ORIGINAL)
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), self.head)
        self.assertEqual((Path(receipt["worktree"]) / "src/calc.py").read_bytes(), PATCH)
        self.assertTrue(Path(receipt["backup_path"]).is_file())
        self.assertFalse(receipt["published"])
        outcome = self.svc.rollback(self.owner, self.sid)
        self.assertEqual(outcome["status"], "rolled_back")
        self.assertEqual((self.repo / "src/calc.py").read_bytes(), ORIGINAL)
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), self.head)
        self.assertEqual(git(self.repo, "status", "--porcelain"), "")
        self.assertEqual(git(self.repo, "branch", "--list", "jarvis/review-*"), "")
        self.assertFalse(Path(receipt["backup_path"]).exists())

    def test_wrong_hash_or_wrong_owner_cannot_stage(self):
        for owner, sha in (("unknown", self.preview["patched_sha256"]),
                           (self.owner, "0" * 64)):
            with self.subTest(owner=owner, digest=sha), self.assertRaises(ReviewDenied):
                self.svc.stage_git(owner, self.sid, str(self.repo), sha, approved=True)
        self.assertEqual(git(self.repo, "branch", "--list", "jarvis/review-*"), "")
        self.svc.rollback(self.owner, self.sid)

    def test_cannot_stage_when_file_changed_since_zip_review(self):
        (self.repo / "src/calc.py").write_bytes(PATCH)
        with self.assertRaises(ReviewDenied):
            self.svc.stage_git(self.owner, self.sid, str(self.repo),
                               self.preview["patched_sha256"], approved=True)
        self.assertEqual(git(self.repo, "branch", "--list", "jarvis/review-*"), "")
        # Restore test fixture, then discard the ZIP review.
        (self.repo / "src/calc.py").write_bytes(ORIGINAL)
        self.svc.rollback(self.owner, self.sid)

    def test_second_staging_is_rejected_and_git_rollback_is_one_time(self):
        receipt = self.svc.stage_git(
            self.owner, self.sid, str(self.repo),
            self.preview["patched_sha256"], approved=True)
        with self.assertRaises(ReviewDenied):
            self.svc.stage_git(self.owner, self.sid, str(self.repo),
                               self.preview["patched_sha256"], approved=True)
        self.assertTrue(Path(receipt["worktree"]).exists())
        self.svc.rollback(self.owner, self.sid)
        with self.assertRaises(ReviewDenied):
            self.svc.rollback(self.owner, self.sid)


if __name__ == "__main__":
    unittest.main()
