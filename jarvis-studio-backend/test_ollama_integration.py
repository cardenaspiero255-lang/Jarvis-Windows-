"""Local AI health tool exposed without any write or install operation."""
import unittest
from unittest import mock

import actions
from llm import live_tools


class OllamaIntegrationTests(unittest.TestCase):
    def test_local_ai_tool_is_exposed(self):
        names = {d["name"] for d in live_tools.function_declarations(False, False)}
        self.assertIn("check_local_ai", names)
        self.assertIn("local_ai", live_tools.groups_for(
            "Jarvis, comprueba si mi modelo local de Ollama funciona"))

    def test_local_ai_diagnostics_is_read_only(self):
        spec = live_tools.to_spec("check_local_ai", {})
        self.assertEqual(spec["type"], "ollama_diagnostics")
        self.assertFalse(actions.needs_permission(spec)[0])

    def test_unreachable_ollama_is_not_announced_as_success(self):
        with mock.patch("ollama_diagnostics.diagnose", return_value={
            "ok": False, "reachable": False, "models": [],
            "selected_available": False, "message": "Ollama is unavailable."}):
            r = actions.run_action({"type": "ollama_diagnostics"})
        self.assertFalse(r["ok"])
        self.assertIn("unavailable", r["message"])
        self.assertIn("models", r["feed_to_model"]["content"])


if __name__ == "__main__":
    unittest.main()
