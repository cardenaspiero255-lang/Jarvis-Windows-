"""External ZIP review sessions: no execution, no user workspace writes."""
import base64
import io
import time
import unittest
import zipfile
from unittest.mock import Mock

from repository_review_sessions import RepositoryReviewSessions, ReviewDenied


def archive(files=None):
    files = files or {"src/calc.py": "def total(price, qty):\n    return price - qty\n",
                      "README.md": "# Project\n"}
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
        for name, value in files.items():
            zipped.writestr(name, value)
    return output.getvalue()


class ReviewSessionsTests(unittest.TestCase):
    def setUp(self):
        self.svc = RepositoryReviewSessions()

    def test_inspect_is_readonly_and_invalid_inputs_fail_closed(self):
        result = self.svc.inspect("local-client-1", archive())
        self.assertEqual(result["status"], "inspected")
        self.assertEqual(result["file_count"], 2)
        self.assertFalse(result["execution_allowed"])
        self.assertFalse(result["modified_user_repo"])
        for bad in (b"", b"not a zip", archive({"../out.py": "pass\n"})):
            with self.subTest(size=len(bad)), self.assertRaises(ReviewDenied):
                self.svc.inspect("local-client-1", bad)

    def test_proposal_is_not_executed_or_applied_without_approval(self):
        info = self.svc.inspect("desktop-A", archive())
        propose = Mock(return_value='{"replacement":"return qty * price"}')
        review = self.svc.propose("desktop-A", info["session_id"],
                                  "src/calc.py", "total", propose=propose)
        self.assertEqual(review["status"], "review_required")
        self.assertIn("+    return qty * price", review["diff"])
        self.assertEqual(review["verification"], "ast_syntax_only_no_external_tests")
        self.assertEqual(self.svc.status("desktop-A", info["session_id"])["status"], "review_required")
        self.assertFalse(review["execution_allowed"])
        with self.assertRaises(ReviewDenied):
            self.svc.export("desktop-A", info["session_id"])

    def test_approval_creates_copy_with_exact_bytes_and_rollback_revokes_it(self):
        original = archive()
        info = self.svc.inspect("local-1", original)
        review = self.svc.propose("local-1", info["session_id"],
                                  "src/calc.py", "total",
                                  propose=lambda *_:'{"replacement":"return qty * price"}')
        with self.assertRaises(ReviewDenied):
            self.svc.apply_copy("local-1", info["session_id"],
                                "0" * 64, approved=True)
        with self.assertRaises(ReviewDenied):
            self.svc.apply_copy("local-1", info["session_id"],
                                review["patched_sha256"], approved=False)
        approved = self.svc.apply_copy("local-1", info["session_id"],
                                       review["patched_sha256"], approved=True)
        self.assertEqual(approved["status"], "copy_staged")
        self.assertFalse(approved["modified_user_repo"])
        self.assertFalse(approved["execution_allowed"])
        exported = self.svc.export("local-1", info["session_id"])
        data = base64.b64decode(exported["zip_b64"])
        self.assertNotEqual(data, original)
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            self.assertIn(b"return qty * price", z.read("src/calc.py"))
            self.assertEqual(z.read("README.md"), b"# Project\n")
        self.svc.rollback("local-1", info["session_id"])
        with self.assertRaises(ReviewDenied):
            self.svc.export("local-1", info["session_id"])
        with self.assertRaises(ReviewDenied):
            self.svc.apply_copy("local-1", info["session_id"],
                                review["patched_sha256"], approved=True)

    def test_owner_is_isolated_and_forged_sessions_fail(self):
        info = self.svc.inspect("client-A", archive())
        for method in ("status", "rollback", "export"):
            with self.subTest(method=method), self.assertRaises(ReviewDenied):
                getattr(self.svc, method)("client-B", info["session_id"])
        with self.assertRaises(ReviewDenied):
            self.svc.propose("client-B", info["session_id"], "src/calc.py",
                              "total", propose=lambda *_: '{"replacement":"return qty * price"}')

    def test_proposal_is_rejected_if_model_attempts_functions_or_imports(self):
        info = self.svc.inspect("desktop", archive())
        with self.assertRaises(ReviewDenied):
            self.svc.propose("desktop", info["session_id"], "src/calc.py",
                              "total", propose=lambda *_:
                              '{"replacement":"return __import__(\'os\').system(\'id\')"}')
        with self.assertRaises(ReviewDenied):
            self.svc.export("desktop", info["session_id"])

    def test_expired_review_can_never_be_applied(self):
        info = self.svc.inspect("desktop", archive())
        self.svc.propose("desktop", info["session_id"], "src/calc.py",
                          "total", propose=lambda *_:'{"replacement":"return qty * price"}')
        self.svc._sessions[info["session_id"]]["created"] = time.monotonic() - 10000
        with self.assertRaises(ReviewDenied):
            self.svc.status("desktop", info["session_id"])
        with self.assertRaises(ReviewDenied):
            self.svc.export("desktop", info["session_id"])

    def test_no_persistent_files_shell_or_network_in_review_session(self):
        import inspect
        import repository_review_sessions as module
        source = inspect.getsource(module)
        self.assertNotIn("subprocess", source)
        self.assertNotIn("os.system", source)
        self.assertNotIn("zipfile.extractall", source)


if __name__ == "__main__":
    unittest.main()
