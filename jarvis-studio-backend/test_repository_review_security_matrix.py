"""Adversarial regression matrix for real untrusted ZIP ingestion and patch copies."""
import io
import unittest
import zipfile
from unittest.mock import patch

from repository_review_sessions import RepositoryReviewSessions, ReviewDenied


def make_zip(files):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for name, content in files:
            z.writestr(name, content)
    return out.getvalue()


class AdversarialRepositoryReviewTests(unittest.TestCase):
    def setUp(self):
        self.agent = RepositoryReviewSessions()

    def test_unsafe_names_cannot_reach_model_or_filesystem(self):
        bad = (
            "../escape.py", "/abs/file.py", "C:/drive/file.py",
            ".git/hooks/post-checkout.py", "folder/.ssh/id.py",
            "folder/../x.py", "folder/./x.py", "folder//x.py",
            "CON.py", "AUX.txt", "folder/NUL.md", "src/COM1.py",
            "src/name .py", "src/x.py.", "src/%2e%2e/out.py",
            "src/a\x00evil.py", "bad\nname.py",
        )
        for idx, name in enumerate(bad):
            with self.subTest(index=idx, name=repr(name)):
                sample = make_zip([(name, "pass\n")])
                with self.assertRaises(ReviewDenied):
                    self.agent.inspect("trusted-local", sample)
        self.assertEqual(len(self.agent._sessions), 0)

    def test_case_collision_and_duplicate_entry_never_accepted(self):
        for files in (
            [("src/A.py", "pass\n"), ("src/a.py", "pass\n")],
            [("a.py", "pass\n"), ("a.py", "pass\n")],
            [("src/x.py", "pass\n"), ("src/x.py/later.py", "pass\n")],
        ):
            with self.subTest(files=str(files)), self.assertRaises(ReviewDenied):
                self.agent.inspect("trusted-local", make_zip(files))

    def test_high_compression_ratio_and_binary_rejected(self):
        for files in (
            [("src/a.py", "0" * 150000)],
            [("src/a.py", b"\xff\xfe")],
            [("payload.exe", "binary")],
        ):
            with self.subTest(files=[p for p,_ in files]), self.assertRaises(ReviewDenied):
                self.agent.inspect("trusted-local", make_zip(files))

    def test_malformed_header_and_random_bytes_fuzz_fail_without_execution(self):
        import random
        rand = random.Random(23121)
        base = make_zip([("ok.py", "def total(x, y):\n    return x-y\n")])
        cases = [bytes(rand.randrange(256) for _ in range(n))
                 for n in range(1, 120, 11)]
        # Invalid signature or truncated ZIP central directory must fail closed.
        cases.extend([base[:10], base[:45], b"no ZIP" + base[:25]])
        with patch("subprocess.run", side_effect=AssertionError("Host code executed")):
            for blob in cases:
                with self.subTest(size=len(blob)), self.assertRaises(ReviewDenied):
                    self.agent.inspect("trusted-local", blob)

    def test_export_does_not_change_original_even_after_approval(self):
        original = make_zip([
            ("src/math.py", "def total(a, b):\n    return a - b\n"),
            ("info.json", '{"notes":"user stays unchanged"}'),
        ])
        owner = "desktop-client"
        session = self.agent.inspect(owner, original)["session_id"]
        review = self.agent.propose(owner, session, "src/math.py", "total",
                                    propose=lambda *_: '{"replacement":"return b * a"}')
        self.agent.apply_copy(owner, session, review["patched_sha256"], approved=True)
        with zipfile.ZipFile(io.BytesIO(original)) as archive:
            self.assertIn(b"return a - b", archive.read("src/math.py"))
        self.assertEqual(self.agent._sessions[session]["archive"], original)
        self.assertNotEqual(self.agent._sessions[session]["copy"], original)
        self.agent.rollback(owner, session)
        self.assertFalse(self.agent._sessions)

    def test_approval_token_and_identity_are_exact_not_truthy(self):
        original = make_zip([("math.py", "def total(a, b):\n    return a - b\n")])
        sid = self.agent.inspect("desktop1", original)["session_id"]
        review = self.agent.propose("desktop1", sid, "math.py", "total",
                                    propose=lambda *_: '{"replacement":"return a * b"}')
        for approved in ("true", 1, False, None):
            with self.subTest(approved=repr(approved)), self.assertRaises(ReviewDenied):
                self.agent.apply_copy("desktop1", sid, review["patched_sha256"],
                                      approved=approved)
        for digest in (review["patched_sha256"].upper(), "0" * 64, "", None):
            with self.subTest(digest=repr(digest)), self.assertRaises(ReviewDenied):
                self.agent.apply_copy("desktop1", sid, digest, approved=True)
        with self.assertRaises(ReviewDenied):
            self.agent.apply_copy("another-client", sid,
                                  review["patched_sha256"], approved=True)


if __name__ == "__main__":
    unittest.main()
