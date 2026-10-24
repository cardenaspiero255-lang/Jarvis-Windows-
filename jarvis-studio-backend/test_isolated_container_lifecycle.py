"""Adversarial Docker lifecycle tests: resource ceilings, cleanup and output cap."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from isolated_repo_runner import (
    prepare_demo_snapshot, build_container_argv,
    run_container_tests, SandboxError,
)

IMAGE = "python@sha256:" + "a" * 64

class ContainerLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.snapshot = prepare_demo_snapshot(Path(self.temp.name))

    def test_container_is_detached_named_and_has_hard_log_ceiling(self):
        cmd = build_container_argv(self.snapshot, IMAGE, container_name="jarvis-ci-aabb")
        self.assertEqual(cmd[:2], ["docker", "run"])
        self.assertIn("-d", cmd)
        self.assertIn("--name=jarvis-ci-aabb", cmd)
        self.assertIn("--log-driver=local", cmd)
        self.assertIn("--log-opt=max-size=1m", cmd)
        self.assertIn("--log-opt=max-file=1", cmd)
        self.assertIn("--network=none", cmd)
        self.assertIn("--read-only", cmd)
        self.assertIn("--cap-drop=ALL", cmd)
        self.assertIn("--pids-limit=64", cmd)
        self.assertIn("--memory=256m", cmd)
        self.assertIn("--memory-swap=256m", cmd)
        self.assertIn("--cpus=1", cmd)
        self.assertNotIn("--privileged", cmd)
        self.assertNotIn("--rm", cmd)
        with self.assertRaises(SandboxError):
            build_container_argv(self.snapshot, IMAGE, container_name="evil;rm -rf /")

    def test_cleanup_always_runs_after_pass(self):
        commands = []
        def fake_run(args, **kwargs):
            commands.append(args)
            if args[1] == "run":
                return subprocess.CompletedProcess(args, 0, stdout="id123\n", stderr="")
            if args[1] == "wait":
                return subprocess.CompletedProcess(args, 0, stdout="0\n", stderr="")
            if args[1] == "logs":
                return subprocess.CompletedProcess(args, 0, stdout="", stderr="Ran 11 tests\n\nOK")
            if args[1] == "rm":
                return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
            raise AssertionError(args)
        with mock.patch("isolated_repo_runner.subprocess.run", side_effect=fake_run):
            report = run_container_tests(self.snapshot, IMAGE)
        self.assertTrue(report["passed"], report)
        self.assertEqual([x[1] for x in commands], ["run", "wait", "logs", "rm"])
        self.assertIn("-f", commands[-1])
        self.assertTrue(commands[0][3].startswith("--name=jarvis-ci-"))
        self.assertEqual(commands[0][3].split("=", 1)[1], commands[-1][-1])

    def test_timeout_still_forces_container_removal(self):
        commands = []
        def fake_run(args, **kwargs):
            commands.append(args)
            if args[1] == "run":
                return subprocess.CompletedProcess(args, 0, stdout="cid\n", stderr="")
            if args[1] == "wait":
                raise subprocess.TimeoutExpired(args, timeout=kwargs["timeout"])
            if args[1] == "rm":
                return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
            raise AssertionError(args)
        with mock.patch("isolated_repo_runner.subprocess.run", side_effect=fake_run):
            report = run_container_tests(self.snapshot, IMAGE)
        self.assertFalse(report["passed"])
        self.assertEqual(report["status"], "timeout")
        self.assertEqual([x[1] for x in commands], ["run", "wait", "rm"])

    def test_start_failure_still_attempts_force_removal(self):
        commands = []
        def fake_run(args, **kwargs):
            commands.append(args)
            if args[1] == "run":
                raise OSError("docker unavailable")
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="not found")
        with mock.patch("isolated_repo_runner.subprocess.run", side_effect=fake_run):
            report = run_container_tests(self.snapshot, IMAGE)
        self.assertFalse(report["passed"])
        self.assertEqual([x[1] for x in commands], ["run", "rm"])

    def test_log_budget_exceeded_cannot_claim_success(self):
        calls = []
        def fake_run(args, **kwargs):
            calls.append(args[1])
            if args[1] == "run":
                return subprocess.CompletedProcess(args, 0, stdout="id", stderr="")
            if args[1] == "wait":
                return subprocess.CompletedProcess(args, 0, stdout="0", stderr="")
            if args[1] == "logs":
                return subprocess.CompletedProcess(
                    args, 0, stdout="", stderr=("X" * 20000) + "Ran 11 tests\n\nOK")
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        with mock.patch("isolated_repo_runner.subprocess.run", side_effect=fake_run):
            report = run_container_tests(self.snapshot, IMAGE)
        self.assertFalse(report["passed"])
        self.assertEqual(report["status"], "output_limit")
        self.assertEqual(calls[-1], "rm")

    def test_failed_container_is_not_reported_as_passed(self):
        def fake_run(args, **kwargs):
            if args[1] == "run":
                return subprocess.CompletedProcess(args, 0, stdout="id", stderr="")
            if args[1] == "wait":
                return subprocess.CompletedProcess(args, 0, stdout="137\n", stderr="")
            if args[1] == "logs":
                return subprocess.CompletedProcess(args, 0, stdout="", stderr="Ran 11 tests\n\nOK")
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        with mock.patch("isolated_repo_runner.subprocess.run", side_effect=fake_run):
            report = run_container_tests(self.snapshot, IMAGE)
        self.assertFalse(report["passed"])
        self.assertEqual(report["status"], "tests_failed")

    def test_rejects_outside_workflow_snapshot_before_docker(self):
        with mock.patch("isolated_repo_runner.subprocess.run",
                        side_effect=AssertionError("No Docker")):
            with self.assertRaises(SandboxError):
                run_container_tests(self.snapshot / "nope", IMAGE)

if __name__ == "__main__":
    unittest.main()
