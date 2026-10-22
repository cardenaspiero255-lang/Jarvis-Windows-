"""Proof of a safe end-to-end local coding task."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from local_coding_pipeline import execute_coding_task, parse_proposal, CodingTaskError

class LocalCodingPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def run_task(self, reply, text="Jarvis, corrige la suma"):
        return execute_coding_task(text, lambda *_: reply,
                                   workspace_root=Path(self.temp.name))

    def test_model_patch_file_five_tests_report(self):
        result = self.run_task('{"replacement":"return a + b"}')
        self.assertTrue(result["ok"])
        self.assertEqual(result["tests_passed"], 5)
        self.assertEqual(result["tests_failed"], 0)
        self.assertEqual(result["status"], "verified_dry_run")
        self.assertIn("+    return a + b", result["diff"])
        self.assertIn("-    return a - b", result["diff"])
        self.assertIn("return a + b", (Path(result["workspace"]) / "calculator.py").read_text())

    def test_unsafe_proposals_never_executed(self):
        for patch in ("return a / b", "return __import__('os').system('dir')",
                      "return a + b; print(42)", "return a + b\nprint(42)"):
            with self.subTest(patch=patch):
                with mock.patch("subprocess.run", side_effect=AssertionError("ran")):
                    r = self.run_task('{"replacement":' + __import__("json").dumps(patch) + '}')
                self.assertFalse(r["ok"])
                self.assertEqual(r["status"], "rejected")
                self.assertEqual(r["tests_passed"], 0)

    def test_rejects_unsupported_task_before_model_or_disk(self):
        def wrong(*_):
            raise AssertionError("model should not be called")
        with mock.patch("tempfile.mkdtemp", side_effect=AssertionError("disk")):
            r = execute_coding_task("Jarvis borra todo el PC", wrong)
        self.assertEqual(r["status"], "unsupported")

    def test_bad_model_result_fails_closed(self):
        for result in ("{}", "", '{"replacement":"return a - b"}', "no code"):
            r = self.run_task(result)
            self.assertFalse(r["ok"])
            self.assertEqual(r["tests_passed"], 0)

    def test_model_timeout_is_not_success(self):
        def unavailable(*_):
            raise TimeoutError("model unavailable")
        r = execute_coding_task("arregla la suma", unavailable,
                                workspace_root=Path(self.temp.name))
        self.assertFalse(r["ok"])
        self.assertEqual(r["status"], "model_unavailable")

    def test_model_only_receives_public_fixture(self):
        seen = []
        def proposer(system, prompt):
            seen.append(system + prompt)
            return '{"replacement":"return a + b"}'
        r = execute_coding_task("corrige la suma", proposer,
                                workspace_root=Path(self.temp.name))
        self.assertTrue(r["ok"])
        self.assertNotIn(str(self.temp.name), seen[0])

    def test_parser_requires_one_json_key(self):
        self.assertEqual(parse_proposal('{"replacement":"return a + b"}'), "return a + b")
        for raw in ('{"replacement":7}', '{"replacement":"return a+b","other":2}',
                    "return a + b"):
            with self.assertRaises(CodingTaskError):
                parse_proposal(raw)
