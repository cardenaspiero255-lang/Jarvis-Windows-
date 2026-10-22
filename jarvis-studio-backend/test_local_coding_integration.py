"""Voice action consent and real local coding workflow boundaries."""
import json
import unittest
from unittest import mock

import actions
from llm import live_tools


class LocalCoderIntegrationTests(unittest.TestCase):
    def test_tool_declared_and_defaults_to_consent_required(self):
        names = {entry["name"] for entry in live_tools.function_declarations(False, False)}
        self.assertIn("fix_sample_code_locally", names)
        spec = live_tools.to_spec("fix_sample_code_locally", {
            "task": "Jarvis corrige la suma del proyecto de prueba"
        })
        self.assertEqual(spec["type"], "local_coding_demo")
        gated, kind, _message = actions.needs_permission(spec)
        self.assertTrue(gated)
        self.assertEqual(kind, "local_coding")
        self.assertTrue(actions.run_specs([spec])[0]["needs_permission"])

    def test_approved_action_collects_verified_report(self):
        result = {"ok": True, "status": "verified_dry_run", "tests_passed": 5,
                  "tests_failed": 0, "latency_ms": 32, "workspace": "temp-workspace",
                  "diff": "not to cloud", "sha256": "f" * 64}
        with mock.patch("local_coding_pipeline.ollama_proposer",
                        return_value=lambda *_: '{"replacement":"return a + b"}'), \
             mock.patch("local_coding_pipeline.execute_coding_task",
                        return_value=result):
            action = actions.run_action({
                "type": "local_coding_demo",
                "task": "Jarvis corrige la suma del proyecto de prueba",
            })
        self.assertTrue(action["ok"])
        self.assertIn("five", action["message"].lower())
        evidence = json.loads(action["feed_to_model"]["content"])
        self.assertEqual(evidence["tests_passed"], 5)
        self.assertNotIn("diff", evidence)
        self.assertNotIn("workspace", evidence)

    def test_failed_proposal_is_never_reported_successful(self):
        result = {"ok": False, "status": "rejected", "tests_passed": 0,
                  "tests_failed": 0, "message": "Unsafe model proposal rejected."}
        with mock.patch("local_coding_pipeline.ollama_proposer",
                        return_value=lambda *_: '{"replacement":"bad"}'), \
             mock.patch("local_coding_pipeline.execute_coding_task",
                        return_value=result):
            action = actions.run_action({"type": "local_coding_demo",
                                         "task": "arregla la suma"})
        self.assertFalse(action["ok"])
        self.assertIn("rejected", action["message"])
