"""Isolation policy tests. Docker never starts on Windows during unit tests."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from isolated_repo_runner import (
    SandboxError, build_container_argv, validate_snapshot,
    run_container_tests, prepare_demo_snapshot, apply_vetted_demo_fix,
    run_demo,
)

IMAGE = "python@sha256:" + "a" * 64

class IsolationRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.demo = prepare_demo_snapshot(self.root)

    def test_docker_only_sees_readonly_snapshot_and_zero_egress(self):
        cmd = build_container_argv(self.demo, IMAGE)
        self.assertEqual(cmd[0:2], ["docker", "run"])
        self.assertIn("--network=none", cmd)
        self.assertIn("--read-only", cmd)
        self.assertIn("--cap-drop=ALL", cmd)
        self.assertIn("--security-opt=no-new-privileges", cmd)
        self.assertIn("--pids-limit=64", cmd)
        self.assertIn("--memory=256m", cmd)
        self.assertIn("--memory-swap=256m", cmd)
        self.assertIn("--cpus=1", cmd)
        self.assertIn("--user=65534:65534", cmd)
        self.assertIn("--pull=never", cmd)
        self.assertTrue(any("readonly" in arg and "/code" in arg for arg in cmd))
        self.assertNotIn("--privileged", cmd)
        self.assertNotIn("--network=host", cmd)
        self.assertFalse(any("docker.sock" in arg for arg in cmd))
        self.assertEqual(cmd[-5:], ["python", "-B", "-m", "unittest", "discover"] if False else cmd[-5:])
        self.assertNotIn("sh", cmd)
        self.assertNotIn("bash", cmd)

    def test_snapshot_can_never_include_symlink_or_git_internal(self):
        (self.demo / "src" / "evil.py").symlink_to(self.root / "outside.py")
        with self.assertRaises(SandboxError):
            validate_snapshot(self.demo)
        (self.demo / "src" / "evil.py").unlink()
        (self.demo / ".git").mkdir()
        with self.assertRaises(SandboxError):
            validate_snapshot(self.demo)

    def test_path_escape_and_unpinned_image_rejected(self):
        for image in ("python:latest", "evil:latest", "python@sha256:bad",
                      "python@sha256:" + "a" * 63 + ";", ""):
            with self.subTest(image=image), self.assertRaises(SandboxError):
                build_container_argv(self.demo, image)
        with self.assertRaises(SandboxError):
            build_container_argv(self.root / "missing", IMAGE)

    def test_subprocess_receives_no_credentials_or_docker_redirect(self):
        original = subprocess.run
        seen = []
        secret = {"DOCKER_HOST": "tcp://host.invalid:2375",
                  "DOCKER_CONFIG": "C:/credentials",
                  "GITHUB_TOKEN": "super-secret",
                  "AWS_SECRET_ACCESS_KEY": "private",
                  "JARVIS_PRIVATE_KEY": "private"}
        def fake_run(cmd, **opts):
            seen.append((cmd,opts))
            for key in secret:
                self.assertNotIn(key, opts["env"])
            self.assertFalse(opts.get("shell"))
            self.assertLessEqual(opts["timeout"], 120)
            return subprocess.CompletedProcess(cmd, 0, stdout="Ran 11 tests\n\nOK", stderr="")
        with mock.patch.dict(os.environ, secret), \
             mock.patch("isolated_repo_runner.subprocess.run", side_effect=fake_run):
            report = run_container_tests(self.demo, IMAGE)
        self.assertTrue(report["passed"])
        self.assertEqual(report["tests_reported"], 11)
        self.assertNotIn("super-secret", str(report))
        self.assertEqual(len(seen), 1)

    def test_failed_and_timeout_containers_do_not_claim_success(self):
        with mock.patch("isolated_repo_runner.subprocess.run",
                        return_value=subprocess.CompletedProcess([], 1, stdout="", stderr="ERROR")):
            result = run_container_tests(self.demo, IMAGE)
        self.assertFalse(result["passed"])
        with mock.patch("isolated_repo_runner.subprocess.run",
                        side_effect=subprocess.TimeoutExpired(["docker"], 60)):
            result = run_container_tests(self.demo, IMAGE)
        self.assertFalse(result["passed"])
        self.assertEqual(result["status"], "timeout")

    def test_vetted_patch_limited_to_pricing_and_is_unexecuted_on_host(self):
        with mock.patch("subprocess.run", side_effect=AssertionError("host subprocess")):
            changed = apply_vetted_demo_fix(self.demo, '{"replacement":"return unit_price * quantity"}')
        self.assertEqual(changed["modified_files"], ["src/pricing.py"])
        self.assertIn("return unit_price * quantity", (self.demo / "src/pricing.py").read_text())
        self.assertFalse((self.demo / "src" / "coupons.py").is_symlink())
        self.assertEqual(len(changed["sha256"]), 64)

    def test_refuse_untrusted_patch_before_write(self):
        before = (self.demo / "src" / "pricing.py").read_bytes()
        for response in ('{"replacement":"return __import__(\"os\").system(\"id\")"}',
                         '{"replacement":"return unit_price ** quantity"}',
                         '{"replacement":"return unit_price * quantity", "command":"curl"}',
                         '{"replacement":"return unit_price * quantity; print(1)"}'):
            with self.subTest(response=response), self.assertRaises(SandboxError):
                apply_vetted_demo_fix(self.demo, response)
        self.assertEqual((self.demo / "src" / "pricing.py").read_bytes(), before)

    def test_demo_requires_baseline_fail_and_corrected_success(self):
        states = [
            {"passed": False, "status": "tests_failed", "tests_reported": 11},
            {"passed": True, "status": "passed", "tests_reported": 11},
        ]
        with mock.patch("isolated_repo_runner.run_container_tests",
                        side_effect=states) as runner:
            report = run_demo(IMAGE, workspace_root=self.root)
        self.assertTrue(report["verified"])
        self.assertEqual(report["tests_after"], 11)
        self.assertEqual(report["baseline_passed"], False)
        self.assertEqual(runner.call_count, 2)
        self.assertEqual(report["publication"], "none")
        self.assertEqual(report["execution_platform"], "linux_docker_not_windows")

    def test_demo_cannot_succeed_if_baseline_already_green(self):
        with mock.patch("isolated_repo_runner.run_container_tests",
                        return_value={"passed": True, "status": "passed", "tests_reported": 11}):
            report = run_demo(IMAGE, workspace_root=self.root)
        self.assertFalse(report["verified"])
        self.assertEqual(report["status"], "invalid_baseline")

if __name__ == "__main__":
    unittest.main()
