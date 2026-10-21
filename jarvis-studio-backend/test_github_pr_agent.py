"""Regression coverage for the GitHub PR review and gated CI rerun workflow."""
import unittest

from github_pr_agent import inspect_pull_request, rerun_workflow, validate_ref


class FakeAPI:
    def __init__(self, data):
        self.data = data
        self.posts = []

    def get(self, path):
        if path not in self.data:
            raise AssertionError("Unexpected API request: " + path)
        return self.data[path]

    def post(self, path):
        self.posts.append(path)
        return {}


def fixture():
    p = "/repos/octo/app"
    return FakeAPI({
        p + "/pulls/7": {
            "number": 7, "html_url": "https://github.com/octo/app/pull/7",
            "title": "Fix unsafe shell", "state": "open", "changed_files": 1,
            "head": {"sha": "a" * 40}
        },
        p + "/pulls/7/files?per_page=100&page=1": [{
            "filename": "app.py", "status": "modified",
            "patch": "@@ -1 +1 @@\n-old()\n+subprocess.run(command, shell=True)\n+password = 'my-very-secret-value'",
        }],
        p + "/commits/" + "a" * 40 + "/check-runs?per_page=100": {
            "check_runs": [{"name": "unit tests", "status": "completed",
                            "conclusion": "failure"}]
        },
        p + "/actions/runs?head_sha=" + "a" * 40 + "&per_page=30": {
            "workflow_runs": [
                {"id": 44, "head_sha": "a" * 40, "event": "pull_request",
                 "status": "completed", "conclusion": "failure",
                 "html_url": "https://github.com/octo/app/actions/runs/44"}
            ]
        },
        p + "/actions/runs/44": {
            "id": 44, "head_sha": "a" * 40, "event": "pull_request",
            "status": "completed", "conclusion": "failure",
        },
    })


class GitHubReviewTests(unittest.TestCase):
    def test_review_exposes_real_check_status_and_patch(self):
        result = inspect_pull_request("octo/app", 7, fixture())
        self.assertTrue(result["ok"])
        self.assertIn("subprocess.run", result["diff_excerpt"])
        self.assertEqual(result["checks"][0]["conclusion"], "failure")
        self.assertEqual(result["workflow_runs"][0]["id"], 44)

    def test_static_findings_are_labeled_heuristic_and_secrets_are_redacted(self):
        result = inspect_pull_request("octo/app", 7, fixture())
        self.assertTrue(result["findings"])
        self.assertEqual(result["findings"][0]["kind"], "heuristic")
        self.assertNotIn("my-very-secret-value", str(result))

    def test_rejects_repo_and_number_injection(self):
        for name in ("octo/app/../evil", "octo/evil?x=y", "octo;rm/app", ""):
            with self.assertRaises(ValueError):
                validate_ref(name, 7)
        with self.assertRaises(ValueError):
            validate_ref("octo/app", "7;rm -rf")

    def test_review_caps_diff_size(self):
        api = fixture()
        api.data["/repos/octo/app/pulls/7/files?per_page=100&page=1"][0]["patch"] = "+a" * 40000
        result = inspect_pull_request("octo/app", 7, api)
        self.assertLessEqual(len(result["diff_excerpt"]), 24000)
        self.assertTrue(result["diff_truncated"])

    def test_rerun_succeeds_only_for_current_pr_head(self):
        api = fixture()
        result = rerun_workflow("octo/app", 7, 44, api)
        self.assertTrue(result["ok"])
        self.assertEqual(api.posts, ["/repos/octo/app/actions/runs/44/rerun"])

    def test_rerun_rejects_unrelated_or_stale_runs(self):
        for update in ({"head_sha": "b" * 40}, {"event": "schedule"},
                       {"status": "in_progress"}):
            api = fixture()
            api.data["/repos/octo/app/actions/runs/44"].update(update)
            result = rerun_workflow("octo/app", 7, 44, api)
            self.assertFalse(result["ok"])
            self.assertEqual(api.posts, [])

    def test_rerun_rejects_invalid_run_id_without_api(self):
        with self.assertRaises(ValueError):
            rerun_workflow("octo/app", "7", "-1", fixture())


if __name__ == "__main__":
    unittest.main()
