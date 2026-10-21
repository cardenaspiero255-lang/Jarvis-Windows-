"""Inference probe is a permission-gated, bounded diagnostic not a chat request."""
import unittest
from unittest import mock

import actions
from llm import live_tools


class LocalGenerationActionTests(unittest.TestCase):
    def test_probe_tool_needs_authorization(self):
        names = {v["name"] for v in live_tools.function_declarations(False, False)}
        self.assertIn("test_local_ai_generation", names)
        spec = live_tools.to_spec("test_local_ai_generation", {})
        self.assertEqual(spec["type"], "ollama_inference_probe")
        gated, kind, reason = actions.needs_permission(spec)
        self.assertTrue(gated)
        self.assertEqual(kind, "ollama_inference")
        self.assertIn("Ollama", reason)
        self.assertTrue(actions.run_specs([spec])[0]["needs_permission"])

    def test_denied_probe_does_not_issue_network_request(self):
        with mock.patch("ollama_diagnostics.probe_generation",
                        side_effect=AssertionError("network invoked")):
            gated = actions.run_specs([{"type": "ollama_inference_probe"}])
        self.assertTrue(gated[0]["needs_permission"])

    def test_probe_reports_failure_and_does_not_claim_generation(self):
        outcome = {"ok": False, "generated": False, "latency_ms": None,
                   "message": "Local model could not generate."}
        with mock.patch("ollama_diagnostics.probe_generation", return_value=outcome):
            result = actions.run_action({"type": "ollama_inference_probe"})
        self.assertFalse(result["ok"])
        self.assertIn("could not generate", result["message"])
        self.assertIn('"generated": false', result["feed_to_model"]["content"].lower())

    def test_success_report_does_not_forward_generated_text(self):
        outcome = {"ok": True, "generated": True, "latency_ms": 42,
                   "message": "Local model generated a response."}
        with mock.patch("ollama_diagnostics.probe_generation", return_value=outcome):
            result = actions.run_action({"type": "ollama_inference_probe"})
        self.assertTrue(result["ok"])
        self.assertIn('"latency_ms": 42', result["feed_to_model"]["content"])
        self.assertNotIn("READY", str(result))


if __name__ == "__main__":
    unittest.main()
