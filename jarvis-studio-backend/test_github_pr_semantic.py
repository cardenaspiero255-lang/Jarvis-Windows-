"""Safe deeper PR analysis: AST-only, no execution or raw model context."""
import base64
import unittest

from github_pr_semantic import (analyze_python_source, changed_python_lines,
                                analyze_pull_request_python)


class API:
    def __init__(self, files, sources):
        self.files, self.sources, self.paths = files, sources, []

    def get(self, path):
        self.paths.append(path)
        if path == "/repos/octo/app/pulls/8":
            return {"head": {"sha": "d" * 40}, "number": 8,
                    "changed_files": len(self.files)}
        if path == "/repos/octo/app/pulls/8/files?per_page=100&page=1":
            return self.files
        if "/contents/" in path:
            file = path.split("/contents/", 1)[1].split("?ref=", 1)[0]
            source = self.sources[file]
            return {"encoding": "base64",
                    "content": base64.b64encode(source.encode("utf-8")).decode("ascii"),
                    "size": len(source)}
        raise AssertionError("Unexpected GET: " + path)


class SemanticAnalysisTests(unittest.TestCase):
    def test_aliases_and_literal_shell_true_are_detected(self):
        source = "import subprocess as sp\nfrom subprocess import run as do\nsp.run('ls', shell=True)\ndo('ls', shell=True)\n"
        result = analyze_python_source(source, "src/a.py")
        self.assertEqual([r["rule"] for r in result], ["subprocess-shell", "subprocess-shell"])
        self.assertEqual([r["line"] for r in result], [3, 4])
        self.assertNotIn("ls", str(result))

    def test_ignores_comments_strings_and_safe_shell_false(self):
        src = 'import subprocess\nx = "eval(user)"\n# os.system("bad")\nsubprocess.run("safe", shell=False)\n'
        self.assertEqual(analyze_python_source(src, "app.py"), [])

    def test_respects_new_diff_lines_only(self):
        src = "eval(old)\nprint('ok')\neval(new)\n"
        patch = "@@ -2 +2,2 @@\n print('ok')\n+eval(new)\n"
        changed = changed_python_lines(patch)
        self.assertEqual(changed, {3})
        result = analyze_python_source(src, "app.py", changed)
        self.assertEqual([(x["rule"], x["line"]) for x in result], [("dynamic-eval", 3)])

    def test_detects_requests_tls_bypass_and_pickle_deserialization(self):
        src = "import requests as req\nimport pickle as p\nreq.get('https://example.org', verify=False)\np.loads(data)\n"
        result = analyze_python_source(src, "a.py")
        self.assertEqual([x["rule"] for x in result], ["tls-verification-disabled", "pickle-deserialization"])

    def test_without_patch_coverage_must_be_partial(self):
        files = [{"filename": "src/a.py", "status": "modified", "patch": None}]
        result = analyze_pull_request_python("octo/app", 8, API(files, {}))
        self.assertEqual(result["files_analyzed"], 0)
        self.assertEqual(result["unavailable_files"], 1)
        self.assertFalse(result["complete"])

    def test_fetches_head_sha_contents_and_never_executes_code(self):
        files = [{"filename": "src/a.py", "status": "modified",
                  "patch": "@@ -0,0 +1,2 @@\n+import os\n+os.system('danger')"}]
        source = "import os\nos.system('danger')\n"
        api = API(files, {"src/a.py": source})
        result = analyze_pull_request_python("octo/app", 8, api)
        self.assertEqual(result["files_analyzed"], 1)
        self.assertEqual(result["findings"][0]["rule"], "os-system")
        self.assertIn("/repos/octo/app/contents/src/a.py?ref=" + "d" * 40, api.paths)
        self.assertNotIn("danger", str(result))

    def test_malicious_file_path_never_reaches_contents_api(self):
        files = [{"filename": "../../escape.py", "status": "modified",
                  "patch": "@@ -0,0 +1 @@\n+eval(foo)"}]
        result = analyze_pull_request_python("octo/app", 8, API(files, {}))
        self.assertEqual(result["files_analyzed"], 0)
        self.assertFalse(result["complete"])

    def test_budget_enforced_without_hiding_unanalyzed_files(self):
        files = [{"filename": f"x{i}.py", "status": "modified",
                  "patch": "@@ -0,0 +1 @@\n+eval(abc)"} for i in range(31)]
        api = API(files, {f"x{i}.py": "eval(abc)" for i in range(31)})
        report = analyze_pull_request_python("octo/app", 8, api)
        self.assertLessEqual(report["files_analyzed"], 24)
        self.assertFalse(report["complete"])
        self.assertGreater(report["unavailable_files"], 0)

    def test_budget_now_covers_twenty_four_python_files(self):
        files = [{"filename": f"src/{i}.py", "status": "modified",
                  "patch": "@@ -0,0 +1 @@\n+eval(abc)"} for i in range(24)]
        api = API(files, {f"src/{i}.py": "eval(abc)" for i in range(24)})
        report = analyze_pull_request_python("octo/app", 8, api)
        self.assertEqual(report["files_analyzed"], 24)
        self.assertTrue(report["complete"])

    def test_bad_python_syntax_reported_not_dropped(self):
        files = [{"filename": "app.py", "status": "modified",
                  "patch": "@@ -0,0 +1 @@\n+def ("}]
        report = analyze_pull_request_python("octo/app", 8, API(files, {"app.py": "def ("}))
        self.assertEqual(report["parse_failures"], 1)
        self.assertFalse(report["complete"])


if __name__ == "__main__":
    unittest.main()
