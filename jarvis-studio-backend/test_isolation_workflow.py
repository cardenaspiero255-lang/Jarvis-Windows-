"""CI must keep the isolated runner on Linux and without secrets or writes."""
import unittest
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "isolated-linux.yml"

class IsolationWorkflowTests(unittest.TestCase):
    def test_linux_nonprivileged_checkout_is_required(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("runs-on: ubuntu-latest", text)
        self.assertIn("contents: read", text)
        self.assertIn("persist-credentials: false", text)
        self.assertIn("jarvis-studio-backend/isolated_repo_runner.py", text)
        self.assertIn("jarvis-studio-backend/fixtures/isolation_repo/**", text)
        self.assertIn("docker image inspect", text)
        self.assertIn("--ci-demo", text)
        self.assertNotIn("contents: write", text)
        self.assertNotIn("pull-requests: write", text)
        self.assertNotIn("docker.sock", text)
        self.assertNotIn("secrets.", text)

    def test_real_model_and_sandbox_must_share_disposable_linux_runner(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("real-gguf-sandbox:", text)
        self.assertIn("needs: isolated-multimodule-tests", text)
        self.assertIn("./scripts/real-ollama-linux.sh", text)
        self.assertIn("--real-ollama", text)
        self.assertIn("jarvis-gguf-isolated-proof", text)
        self.assertIn("head.repo.full_name == github.repository", text)

    def test_pr_fork_code_does_not_run(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("head.repo.full_name == github.repository", text)
        self.assertIn("permissions:", text)

if __name__ == "__main__":
    unittest.main()
