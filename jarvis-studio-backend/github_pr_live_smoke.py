"""Read-only integration smoke against a live GitHub pull request.

Run only inside the PR CI job with an explicitly scoped GITHUB_TOKEN. This test
never writes to GitHub, executes downloaded code, or prints source/credentials.
"""
import os
import sys

from github_pr_agent import GitHubAPI, inspect_pull_request, model_evidence
from github_pr_semantic import analyze_pull_request_python


class ReadOnlyGitHub(GitHubAPI):
    def post(self, path):
        raise AssertionError("E2E inspection attempted a GitHub write.")

    def _request(self, path, method):
        if method != "GET":
            raise AssertionError("E2E allows GET only.")
        return super()._request(path, method)


def main():
    repo = os.environ["JARVIS_E2E_REPOSITORY"]
    pr_number = int(os.environ["JARVIS_E2E_PR"])
    expected_sha = os.environ["JARVIS_E2E_HEAD_SHA"]
    if not os.environ.get("GITHUB_TOKEN"):
        raise RuntimeError("No read-only GitHub token configured for the E2E.")
    api = ReadOnlyGitHub()
    report = inspect_pull_request(repo, pr_number, api=api)
    if report["head_sha"] != expected_sha:
        raise RuntimeError("PR head has changed; E2E must be rerun for new head.")
    if not report["files_inspected"] or not report["checks"]:
        raise RuntimeError("Live GitHub returned no changed files or commit checks.")
    semantic = analyze_pull_request_python(repo, pr_number, api=api)
    report["semantic_analysis"] = semantic
    evidence = model_evidence(report)
    prohibited = ("diff_excerpt", "title", "source_code", "raw_patch", "raw_source")
    if any(k in evidence for k in prohibited):
        raise RuntimeError("Potential raw source field forwarded in E2E model evidence.")
    if evidence["head_sha"] != expected_sha:
        raise RuntimeError("Evidence refers to the wrong commit.")
    if semantic["python_candidates"] < 1 or semantic["files_analyzed"] < 1:
        raise RuntimeError("The live PR had no analyzable Python changes.")
    if semantic["files_analyzed"] > 12 or len(semantic["findings"]) > 60:
        raise RuntimeError("The AST analysis escaped its resource budget.")
    print("PASS: live authenticated, read-only GitHub PR inspection")
    print("HEAD verified; files checked:", report["files_inspected"],
          "incomplete coverage:", not report["file_coverage_complete"],
          "check count:", len(report["checks"]))
    print("AST Python files analyzed:", semantic["files_analyzed"],
          "AST heuristic findings:", len(semantic["findings"]),
          "AST complete:", semantic["complete"])
    # NEVER print raw patch, source code, model evidence or credential values.
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as err:
        # Prevent potential HTTP exception strings from reaching public logs.
        print("FAIL: read-only GitHub E2E did not meet its invariants. Error type:",
              type(err).__name__)
        sys.exit(1)
