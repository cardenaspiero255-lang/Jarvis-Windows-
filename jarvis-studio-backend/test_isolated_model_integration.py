"""Real-model proposal must drive the isolated Linux fail-then-pass check."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from isolated_repo_runner import run_demo

IMAGE = "python@sha256:" + "a" * 64

class ModelSandboxIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def test_trusted_model_proposal_is_used_before_second_container(self):
        stages = [
            {"passed": False, "status": "tests_failed", "tests_reported": 11,
             "container_cleaned": True},
            {"passed": True, "status": "passed", "tests_reported": 11,
             "container_cleaned": True},
        ]
        seen = []
        def proposer(system, prompt):
            seen.append((system,prompt))
            return '{"replacement":"return unit_price * quantity"}'
        with mock.patch("isolated_repo_runner.run_container_tests",
                        side_effect=stages) as run:
            result = run_demo(IMAGE, workspace_root=Path(self.temp.name),
                              proposer=proposer)
        self.assertTrue(result["verified"])
        self.assertEqual(result["model_source"], "local_ollama_gguf")
        self.assertEqual(len(seen), 1)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(result["publication"], "none")
        self.assertTrue(result["all_containers_cleaned"])

    def test_model_failure_does_not_run_second_container(self):
        def bad(*_):
            return '{"replacement":"return __import__(\"os\").system(\"id\")"}'
        with mock.patch("isolated_repo_runner.run_container_tests",
                        return_value={"passed": False, "status": "tests_failed",
                                      "tests_reported": 11,
                                      "container_cleaned": True}) as run:
            result = run_demo(IMAGE, workspace_root=Path(self.temp.name),
                              proposer=bad)
        self.assertFalse(result["verified"])
        self.assertEqual(result["status"], "proposal_rejected")
        self.assertEqual(run.call_count, 1)

    def test_unclean_first_container_blocks_model_call(self):
        with mock.patch("isolated_repo_runner.run_container_tests",
                        return_value={"passed": False, "status": "cleanup_failed",
                                      "tests_reported": 11,
                                      "container_cleaned": False}):
            result = run_demo(IMAGE, workspace_root=Path(self.temp.name),
                              proposer=lambda *_: self.fail("model called"))
        self.assertFalse(result["verified"])
        self.assertEqual(result["status"], "invalid_baseline")

    def test_model_timeout_keeps_report_negative(self):
        with mock.patch("isolated_repo_runner.run_container_tests",
                        return_value={"passed": False, "status": "tests_failed",
                                      "tests_reported": 11,
                                      "container_cleaned": True}):
            report = run_demo(IMAGE, workspace_root=Path(self.temp.name),
                proposer=lambda *_: (_ for _ in ()).throw(TimeoutError("offline")))
        self.assertFalse(report["verified"])
        self.assertEqual(report["status"], "model_unavailable")

if __name__ == "__main__":
    unittest.main()
