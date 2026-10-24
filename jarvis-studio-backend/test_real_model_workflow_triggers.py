"""Regression that real GGUF Windows E2E reruns when the agent changes."""
import re
import unittest
from pathlib import Path

WORKFLOW = (Path(__file__).resolve().parents[1]
            / ".github" / "workflows" / "real-model-windows.yml")
# Every file able to change the actual model -> validated Git patch path.
MUST_TRIGGER = {
    "jarvis-studio-backend/controlled_repository_agent.py",
    "jarvis-studio-backend/test_controlled_repository_agent.py",
    "jarvis-studio-backend/test_controlled_repository_security.py",
    "jarvis-studio-backend/test_controlled_repository_integration.py",
    "jarvis-studio-backend/fixtures/controlled_repo/**",
    "jarvis-studio-backend/real_local_model_e2e.py",
    "jarvis-studio-backend/test_real_local_model_e2e.py",
    "jarvis-studio-backend/local_coding_pipeline.py",
    "jarvis-studio-backend/ollama_diagnostics.py",
    "jarvis-studio-backend/actions/__init__.py",
    "jarvis-studio-backend/llm/live_tools.py",
    "scripts/real-ollama-windows.ps1",
}

class ModelWorkflowCoverageTests(unittest.TestCase):
    def test_all_security_sensitive_changes_trigger_real_model_job(self):
        content = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("  pull_request:", content)
        self.assertIn("branches: [main]", content)
        paths = set(re.findall(r"^\s+-\s+'([^']+)'\s*$", content, re.M))
        self.assertFalse(MUST_TRIGGER - paths, sorted(MUST_TRIGGER - paths))

    def test_real_model_workflow_is_read_only_and_fork_restricted(self):
        content = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("contents: read", content)
        self.assertIn("head.repo.full_name == github.repository", content)
        self.assertNotIn("pull-requests: write", content)
        self.assertNotIn("contents: write", content)

if __name__ == "__main__":
    unittest.main()
