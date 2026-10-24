"""Adversarial regression tests for approved, disposable Git coding tasks.

These assertions deliberately reject inherited Git environment directives
before ever allowing the wrapped Git process to execute.
"""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from controlled_repository_agent import repair_controlled_repository

_GIT_INJECTION = {
    "GIT_DIR": "elsewhere/.git",
    "GIT_WORK_TREE": "elsewhere",
    "GIT_INDEX_FILE": "elsewhere/index",
    "GIT_COMMON_DIR": "elsewhere/common",
    "GIT_OBJECT_DIRECTORY": "elsewhere/objects",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES": "elsewhere/alternates",
    "GIT_TEMPLATE_DIR": "elsewhere/templates",
    "GIT_EXEC_PATH": "elsewhere/executables",
    "GIT_CONFIG_COUNT": "1",
    "GIT_CONFIG_KEY_0": "core.hooksPath",
    "GIT_CONFIG_VALUE_0": "elsewhere/hooks",
    "GIT_CONFIG_PARAMETERS": "'core.hooksPath=elsewhere/hooks'",
    "GIT_CONFIG_SYSTEM": "elsewhere/gitconfig",
    "GIT_TRACE": "elsewhere/trace",
    "GIT_SSH_COMMAND": "evil",
    "JARVIS_TEST_SECRET": "should-not-be-passed-to-git",
}

class ControlledGitSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.parent = Path(self.temp.name)
        self.good = '{"replacement":"return unit_price * quantity"}'

    def test_injected_git_env_never_crosses_subprocess_boundary(self):
        original_run = subprocess.run
        calls = []
        def checked_run(args, *positional, **kw):
            env = kw["env"]
            calls.append(args)
            for name in _GIT_INJECTION:
                self.assertNotIn(name, env, f"Unexpected inherited key: {name}")
            self.assertEqual(env.get("GIT_CONFIG_NOSYSTEM"), "1")
            self.assertEqual(env.get("GIT_TERMINAL_PROMPT"), "0")
            self.assertEqual(env.get("GIT_CONFIG_GLOBAL"), os.devnull)
            self.assertTrue(Path(env["HOME"]).is_dir())
            self.assertTrue(Path(env["HOME"]).is_relative_to(Path(kw["cwd"])))
            self.assertFalse(kw.get("shell", False))
            self.assertIsInstance(args, list)
            return original_run(args, *positional, **kw)
        with mock.patch.dict(os.environ, _GIT_INJECTION), \
             mock.patch("controlled_repository_agent.subprocess.run",
                        side_effect=checked_run):
            result = repair_controlled_repository(
                "corrige el total del proyecto de prueba",
                lambda *_: self.good, workspace_root=self.parent)
        self.assertTrue(result["ok"], result)
        self.assertGreaterEqual(len(calls), 5)
        self.assertFalse((self.parent / "elsewhere").exists())

    def test_rooted_windows_posix_relative_and_unc_paths_are_rejected(self):
        commands = (
            "corrige total en C:/Users/Private/code.py",
            r"corrige el total C:\Users\Private\code.py",
            r"corrige total ..\Private\secrets.py",
            "corrige el total ../Private/secrets.py",
            "corrige total /etc/passwd",
            "corrige total //server/share",
            r"corrige total \\server\share",
            "corrige total file:///private/records",
            "corrige total ~/projects/private",
            "corrige total src/totals.py",
            "corrige total y haz git push",
            "corrige total y publícalo",
            "corrige total y clona otro repo",
        )
        for command in commands:
            with self.subTest(command=command), \
                 mock.patch("tempfile.mkdtemp",
                            side_effect=AssertionError("Unexpected disk write")), \
                 mock.patch("subprocess.run",
                            side_effect=AssertionError("Unexpected Git execution")):
                result = repair_controlled_repository(
                    command, lambda *_: self.fail("LLM must not be called"),
                    workspace_root=self.parent)
            self.assertEqual(result["status"], "unsupported", command)
            self.assertFalse(result["ok"])

    def test_simple_speech_requests_still_pass(self):
        for command, model_response in (
            ("JARVIS, corrige el total del repositorio de prueba",
             '{"replacement":"return unit_price * quantity"}'),
            ("Corrige el descuento del repositorio de prueba",
             '{"replacement":"return subtotal - subtotal * percent / 100"}'),
        ):
            with self.subTest(command=command):
                result = repair_controlled_repository(
                    command, lambda *_: model_response, workspace_root=self.parent)
                self.assertTrue(result["ok"], result)
                self.assertEqual(result["tests_passed"], 7)

if __name__ == "__main__":
    unittest.main()
