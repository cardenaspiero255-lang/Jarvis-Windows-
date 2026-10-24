"""TDD contract for a disposable two-file Git repository coding agent.

The exercise must NEVER clone a user repo, execute untrusted code, make a
network request, install tools, or publish/commit the generated patch.
"""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from controlled_repository_agent import repair_controlled_repository

GOOD = {
    "total": '{"replacement":"return unit_price * quantity"}',
    "descuento": '{"replacement":"return subtotal - subtotal * percent / 100"}',
}

class ControlledRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_model_fixes_real_file_on_isolated_git_branch(self):
        seen = []
        def proposer(system, prompt):
            seen.append(system + "\n" + prompt)
            return GOOD["total"]
        report = repair_controlled_repository("JARVIS, corrige el total del proyecto",
                                              proposer, workspace_root=self.root)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["status"], "verified_local_branch")
        self.assertEqual(report["tests_failed"], 0)
        self.assertGreaterEqual(report["tests_passed"], 6)
        self.assertEqual(report["modified_files"], ["src/totals.py"])
        self.assertTrue(report["branch"].startswith("jarvis/demo-"))
        self.assertIn("return unit_price * quantity", report["diff"])
        self.assertIn("return unit_price * quantity",
                      (Path(report["workspace"]) / "src/totals.py").read_text())
        self.assertEqual(len(seen), 1)
        self.assertNotIn(str(self.root), seen[0])
        # HEAD and main are identical, so the patch has not been committed.
        cwd = report["workspace"]
        def git(*args):
            return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()
        self.assertEqual(git("remote"), "")
        self.assertEqual(git("log", "--format=%H", "main..HEAD"), "")
        self.assertEqual(git("show", "main:src/totals.py").splitlines()[-1],
                         "    return unit_price - quantity")
        self.assertEqual(git("diff", "--name-only"), "src/totals.py")

    def test_discount_is_distinct_task_and_does_not_modify_totals(self):
        report = repair_controlled_repository("Corrige el descuento del repositorio de prueba",
                                              lambda *_: GOOD["descuento"],
                                              workspace_root=self.root)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["modified_files"], ["src/discounts.py"])
        self.assertGreaterEqual(report["tests_passed"], 6)
        self.assertIn("return unit_price - quantity",
                      (Path(report["workspace"]) / "src/totals.py").read_text())

    def test_unsafe_proposals_fail_before_git_and_disk_write(self):
        for response in (
            '{"replacement":"return __import__(\"os\").system(\"del C:\")"}',
            '{"replacement":"return open(\"C:/secret\").read()"}',
            '{"replacement":"return unit_price * quantity; print(2)"}',
            '{"replacement":"return unit_price ** quantity"}',
            '{"replacement":"return unit_price * (quantity + 0)\nexec(x)"}',
            '{"replacement":"return unit_price * quantity", "command":"git push"}',
        ):
            with self.subTest(response=response), mock.patch("subprocess.run",
                              side_effect=AssertionError("untrusted code executed")):
                report = repair_controlled_repository("corrige el total",
                                                       lambda *_: response,
                                                       workspace_root=self.root)
            self.assertFalse(report["ok"])
            self.assertEqual(report["tests_passed"], 0)
            self.assertNotEqual(report["status"], "verified_local_branch")

    def test_wrong_but_safe_math_fails_tests_no_branch_or_write(self):
        with mock.patch("subprocess.run", side_effect=AssertionError("git called")):
            report = repair_controlled_repository("arregla el total",
                            lambda *_: '{"replacement":"return unit_price + quantity"}',
                            workspace_root=self.root)
        self.assertFalse(report["ok"])
        self.assertEqual(report["status"], "tests_failed")
        self.assertGreater(report["tests_failed"], 0)

    def test_unknown_task_never_asks_model_or_touches_files(self):
        with mock.patch("subprocess.run", side_effect=AssertionError("git called")), \
             mock.patch("tempfile.mkdtemp", side_effect=AssertionError("disk touched")):
            report = repair_controlled_repository(
                "JARVIS, modifica C:/Users/private/credentials.py y haz push",
                lambda *_: self.fail("LLM must not run"),
                workspace_root=self.root)
        self.assertEqual(report["status"], "unsupported")
        self.assertFalse(report["ok"])

    def test_model_error_reports_fail_closed(self):
        def offline(*_):
            raise TimeoutError("no Internet")
        result = repair_controlled_repository("corrige descuento", offline,
                                              workspace_root=self.root)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "model_unavailable")

    def test_fixture_tampering_blocks_branch_creation(self):
        from controlled_repository_agent import FIXTURE_ROOT
        with mock.patch("controlled_repository_agent.FIXTURE_ROOT",
                        self.root / "not-a-fixture"):
            with mock.patch("subprocess.run", side_effect=AssertionError("git called")):
                result = repair_controlled_repository("corrige el total",
                    lambda *_: GOOD["total"], workspace_root=self.root)
        self.assertEqual(result["status"], "fixture_invalid")

    def test_git_invocations_use_fixed_argument_vectors_without_shell(self):
        original = subprocess.run
        seen = []
        def guard(args, *a, **kw):
            self.assertIsInstance(args, list)
            self.assertEqual(args[0], "git")
            self.assertFalse(kw.get("shell", False))
            self.assertNotIn("push", args)
            self.assertNotIn("fetch", args)
            self.assertNotIn("clone", args)
            seen.append(args)
            return original(args, *a, **kw)
        with mock.patch("controlled_repository_agent.subprocess.run", side_effect=guard):
            result = repair_controlled_repository("corrige el total",
                        lambda *_: GOOD["total"], workspace_root=self.root)
        self.assertTrue(result["ok"], result)
        self.assertGreaterEqual(len(seen), 4)

if __name__ == "__main__":
    unittest.main()
