"""Integration contract: JARVIS must approve before controlled Git demo."""
import json
import unittest
from unittest import mock

import actions
from llm import live_tools


class ControlledRepoActionTests(unittest.TestCase):
    def test_voice_tool_declared_and_gated(self):
        names = {x["name"] for x in live_tools.function_declarations(False, False)}
        self.assertIn("repair_controlled_repository", names)
        spec = live_tools.to_spec("repair_controlled_repository",
             {"task": "JARVIS, corrige el total del repo de prueba"})
        self.assertEqual(spec["type"], "controlled_repo_repair")
        self.assertEqual(actions.needs_permission(spec)[1], "local_coding")
        self.assertTrue(actions.run_specs([spec])[0]["needs_permission"])

    def test_denial_cannot_call_model_or_git(self):
        spec = {"type": "controlled_repo_repair", "task": "corrige el total"}
        with mock.patch("controlled_repository_agent.repair_controlled_repository",
                        side_effect=AssertionError("should never run")):
            gated = actions.run_specs([spec])[0]
        self.assertTrue(gated["needs_permission"])

    def test_approved_action_only_reports_allowlisted_receipt(self):
        fake = {"ok": True, "status": "verified_local_branch",
                "message": "Passed", "tests_passed": 7, "tests_failed": 0,
                "modified_files": ["src/totals.py"], "source_sha256": "a" * 64,
                "branch": "jarvis/demo-012345", "workspace": "C:/Secret Directory",
                "diff": "SECRET-SOURCE-CONTENT", "published": False,
                "modified_user_repo": False}
        with mock.patch("local_coding_pipeline.ollama_proposer",
                        return_value=lambda *_: "{}"), \
             mock.patch("controlled_repository_agent.repair_controlled_repository",
                        return_value=fake):
            result = actions.run_action(
                {"type": "controlled_repo_repair", "task": "corrige el total"})
        self.assertTrue(result["ok"])
        info = json.loads(result["feed_to_model"]["content"])
        self.assertEqual(info["tests_passed"], 7)
        self.assertFalse(info["published"])
        self.assertEqual(info["modified_files"], ["src/totals.py"])
        self.assertNotIn("SECRET-SOURCE-CONTENT", str(result))
        self.assertNotIn("Secret Directory", str(result))
        self.assertNotIn("workspace", info)
        self.assertNotIn("diff", info)

    def test_no_success_claim_when_model_fails(self):
        with mock.patch("local_coding_pipeline.ollama_proposer",
                        return_value=lambda *_: "{}"), \
             mock.patch("controlled_repository_agent.repair_controlled_repository",
                        return_value={"ok": False, "status": "tests_failed",
                                      "message": "Checks failed", "tests_passed": 2,
                                      "tests_failed": 5, "published": False}):
            outcome = actions.run_action(
                {"type": "controlled_repo_repair", "task": "corrige descuento"})
        self.assertFalse(outcome["ok"])
        self.assertEqual(json.loads(outcome["feed_to_model"]["content"])["tests_failed"], 5)

if __name__ == "__main__":
    unittest.main()
