"""End-to-end (mocked network) path: voice tool -> action -> permission gate."""
import unittest
from unittest import mock

import actions
from llm import live_tools


class GitHubIntegrationTests(unittest.TestCase):
    def test_pr_review_is_exposed_to_voice_model(self):
        names = {d["name"] for d in live_tools.function_declarations(False, False)}
        self.assertIn("github_pr_review", names)
        self.assertIn("github_pr_rerun_ci", names)

    def test_spanish_pr_request_loads_github_group(self):
        self.assertIn("github", live_tools.groups_for(
            "Jarvis, revisa el PR 202 de GameHub Ultra en GitHub"))

    def test_review_tool_resolves_to_read_only_action(self):
        spec = live_tools.to_spec("github_pr_review", {"repo": "octo/app", "pr": 7})
        self.assertEqual(spec, {"type": "github_pr_inspect", "repo": "octo/app", "pr": 7})
        self.assertFalse(actions.needs_permission(spec)[0])

    def test_ci_rerun_requires_approval(self):
        spec = live_tools.to_spec("github_pr_rerun_ci",
                                  {"repo": "octo/app", "pr": 7, "run_id": 44})
        self.assertEqual(spec["type"], "github_ci_rerun")
        gated, kind, reason = actions.needs_permission(spec)
        self.assertTrue(gated)
        self.assertEqual(kind, "github_ci")
        self.assertIn("run 44", reason)
        self.assertTrue(actions.run_specs([spec])[0]["needs_permission"])

    def test_read_only_review_provides_evidence_to_model(self):
        mock_report = {"number": 7, "repository": "octo/app", "ok": True,
                       "diff_excerpt": "+shell=True", "checks": []}
        with mock.patch("github_pr_agent.inspect_pull_request", return_value=mock_report):
            outcome = actions.run_specs([{
                "type": "github_pr_inspect", "repo": "octo/app", "pr": 7
            }])[0]
        self.assertTrue(outcome["ok"])
        self.assertIn("shell=True", outcome["feed_to_model"]["content"])
        self.assertEqual(outcome["speak"], "")

    def test_action_returns_failure_instead_of_announcing_success(self):
        from github_pr_agent import APIError
        with mock.patch("github_pr_agent.inspect_pull_request",
                        side_effect=APIError("GitHub returned HTTP 403.")):
            outcome = actions.run_action({
                "type": "github_pr_inspect", "repo": "octo/app", "pr": 7
            })
        self.assertFalse(outcome["ok"])
        self.assertIn("403", outcome["message"])


if __name__ == "__main__":
    unittest.main()
