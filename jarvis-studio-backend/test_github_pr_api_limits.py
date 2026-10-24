"""Regression: large 100-file GitHub PR pages must be handled with strict caps."""
import io
import json
import unittest
from unittest import mock

from github_pr_agent import GitHubAPI, APIError


class Response:
    def __init__(self, raw):
        self.buffer = io.BytesIO(raw)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, size=-1):
        return self.buffer.read(size)


class APIResponseSizeTests(unittest.TestCase):
    def test_realistic_large_pr_files_page_under_four_megabytes(self):
        # Real JARVIS PR #1 exceeded the original 700 kB API response cap.
        payload = {"files": ["x" * 925000]}
        raw = json.dumps(payload).encode("utf-8")
        with mock.patch("github_pr_agent.urlopen", return_value=Response(raw)):
            got = GitHubAPI().get("/repos/octo/app/pulls/1/files?per_page=100&page=1")
        self.assertEqual(got, payload)

    def test_large_non_file_api_response_is_still_rejected(self):
        raw = json.dumps({"contents": "z" * 900000}).encode("utf-8")
        with mock.patch("github_pr_agent.urlopen", return_value=Response(raw)):
            with self.assertRaises(APIError):
                GitHubAPI().get("/repos/octo/app/pulls/1")

    def test_file_list_still_rejects_more_than_four_megabytes(self):
        raw = json.dumps({"files": ["x" * 4200000]}).encode("utf-8")
        with mock.patch("github_pr_agent.urlopen", return_value=Response(raw)):
            with self.assertRaises(APIError):
                GitHubAPI().get("/repos/octo/app/pulls/1/files?per_page=100&page=1")


if __name__ == "__main__":
    unittest.main()
