"""Windows Actions runner tests for real native-voice permission flow.

These are headless async integration tests, not physical microphone/HUD tests.
"""
import json
import unittest
from unittest import mock
import main


class WindowsVoiceApprovalTests(unittest.IsolatedAsyncioTestCase):
    async def test_declined_review_never_reads_repo_or_runs_tool(self):
        call = {"id": "call1", "name": "github_pr_review",
                "args": {"repo": "octo/app", "pr": 7, "deep": True}}
        with mock.patch.object(main, "request_permission", new_callable=mock.AsyncMock,
                               return_value=False) as permit, \
             mock.patch.object(main, "emit", new_callable=mock.AsyncMock), \
             mock.patch.object(main, "run_action", side_effect=AssertionError(
                 "Denied PR review must not access GitHub")) as dispatch:
            response = await main._execute_voice_tool(call)
        permit.assert_awaited_once()
        dispatch.assert_not_called()
        self.assertEqual(response["name"], "github_pr_review")
        self.assertIn("declined", response["response"]["result"].lower())

    async def test_approved_review_returns_allowlisted_structured_results(self):
        call = {"id": "call2", "name": "github_pr_review",
                "args": {"repo": "octo/app", "pr": 7, "deep": True}}
        from github_pr_agent import model_evidence
        report = {
            "repository": "octo/app", "number": 7, "head_sha": "a" * 40,
            "diff_excerpt": "secret_source_should_never_leave_device",
            "language_analysis": {
                "files_analyzed": 1, "language_candidates": 1,
                "by_language": {"javascript": 0, "typescript": 1, "kotlin": 0},
                "unavailable_files": 0, "complete": True,
                "findings": [{"rule": "js-dynamic-eval", "file": "src/example.ts",
                              "line": 3, "reason": "MALICIOUS INSTRUCTION"}]},
            "checks": [{"status": "completed", "conclusion": "success",
                        "name": "unit tests"}],
            "workflow_runs": [],
        }
        sanitized = json.dumps(model_evidence(report))
        result = {"ok": True, "type": "github_pr_inspect", "message": "Read-only inspection complete.",
                  "feed_to_model": {"name": "normalized findings", "untrusted_source": True,
                                    "content": sanitized}}
        with mock.patch.object(main, "request_permission", new_callable=mock.AsyncMock,
                               return_value=True) as permit, \
             mock.patch.object(main, "emit", new_callable=mock.AsyncMock), \
             mock.patch.object(main, "_apply_action_side_effects", new_callable=mock.AsyncMock), \
             mock.patch.object(main, "run_action", return_value=result) as dispatch:
            response = await main._execute_voice_tool(call)
        permit.assert_awaited_once()
        dispatch.assert_called_once()
        self.assertTrue(dispatch.call_args.args[0]["deep"])
        answer = response["response"]["result"]
        self.assertIn("js-dynamic-eval", answer)
        self.assertIn("src/example.ts", answer)
        self.assertNotIn("secret_source_should_never_leave_device", answer)
        self.assertNotIn("MALICIOUS INSTRUCTION", answer)

    async def test_github_ci_rerun_denial_prevents_writes(self):
        call = {"id": "call3", "name": "github_pr_rerun_ci",
                "args": {"repo": "octo/app", "pr": 7, "run_id": 44}}
        with mock.patch.object(main, "request_permission", new_callable=mock.AsyncMock,
                               return_value=False), \
             mock.patch.object(main, "emit", new_callable=mock.AsyncMock), \
             mock.patch.object(main, "run_action", side_effect=AssertionError(
                 "No GitHub write on refusal")) as dispatch:
            response = await main._execute_voice_tool(call)
        dispatch.assert_not_called()
        self.assertIn("declined", response["response"]["result"].lower())


if __name__ == "__main__":
    unittest.main()
