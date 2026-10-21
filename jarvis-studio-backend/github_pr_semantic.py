"""Bounded semantic PR diagnostics using Python AST, never executing PR code.

Only GitHub's immutable PR HEAD SHA is read. Analysis is syntactic, not a
vulnerability verdict. Source text is never sent to the language model.
"""
from __future__ import annotations

import ast
import base64
import binascii
import re
from urllib.parse import quote

_MAX_FILES = 24
_MAX_BYTES = 160_000
_MAX_PATCH_BYTES = 240_000
_SAFE_PATH = re.compile(r"^[A-Za-z0-9_./-]{1,180}$")
_HUNK = re.compile(r"^@@\s+-\d+(?:,\d+)?\s+\+(\d+)(?:,\d+)?\s+@@")
_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
_REPO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")

_RULES = {
    "subprocess-shell": "Subprocess shell execution requires review.",
    "dynamic-eval": "Dynamic Python expression evaluation requires review.",
    "dynamic-exec": "Dynamic Python code execution requires review.",
    "os-system": "A shell command is executed through os.system.",
    "tls-verification-disabled": "TLS certificate validation may be disabled.",
    "pickle-deserialization": "Untrusted pickle deserialization is unsafe.",
}


def _call_name(call, aliases):
    target = call.func
    if isinstance(target, ast.Name):
        return aliases.get(target.id, target.id)
    if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
        module = aliases.get(target.value.id, target.value.id)
        return module + "." + target.attr
    return ""


def analyze_python_source(source, filename, changed_lines=None):
    """Return bounded AST findings without quoting source lines or string literals."""
    tree = ast.parse(source)
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                if item.name in ("subprocess", "requests", "pickle", "os"):
                    aliases[item.asname or item.name] = item.name
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module in ("subprocess", "requests", "pickle", "os"):
                for item in node.names:
                    aliases[item.asname or item.name] = node.module + "." + item.name
    findings = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if changed_lines is not None and node.lineno not in changed_lines:
            continue
        callee = _call_name(node, aliases)
        options = {kw.arg: kw.value for kw in node.keywords if kw.arg}
        rule = ""
        if callee in ("eval", "builtins.eval"):
            rule = "dynamic-eval"
        elif callee in ("exec", "builtins.exec"):
            rule = "dynamic-exec"
        elif callee == "os.system":
            rule = "os-system"
        elif callee.startswith("subprocess.") and callee.rsplit(".", 1)[-1] in (
            "run", "call", "check_call", "check_output", "Popen"
        ) and isinstance(options.get("shell"), ast.Constant) and options["shell"].value is True:
            rule = "subprocess-shell"
        elif callee.startswith("requests.") and callee.rsplit(".", 1)[-1] in (
            "get", "post", "put", "patch", "delete", "request", "head"
        ) and isinstance(options.get("verify"), ast.Constant) and options["verify"].value is False:
            rule = "tls-verification-disabled"
        elif callee in ("pickle.load", "pickle.loads"):
            rule = "pickle-deserialization"
        if rule:
            findings.append({"rule": rule, "file": filename, "line": node.lineno,
                             "kind": "AST heuristic", "reason": _RULES[rule]})
    return sorted(findings, key=lambda x: (x["line"], x["rule"]))[:40]


def changed_python_lines(patch):
    """Parse *new* line numbers in the GitHub unified diff; never run diff text."""
    result = set()
    cursor = None
    for row in patch.splitlines():
        hunk = _HUNK.match(row)
        if hunk:
            cursor = int(hunk.group(1))
            continue
        if cursor is None:
            continue
        if row.startswith("+") and not row.startswith("+++"):
            result.add(cursor)
            cursor += 1
        elif row.startswith(" "):
            cursor += 1
        elif row.startswith("-") or row.startswith("\\"):
            pass
        else:
            cursor = None
    return result


def _safe_path(path):
    return (isinstance(path, str) and bool(_SAFE_PATH.fullmatch(path))
            and not path.startswith("/") and not any(p in ("", ".", "..")
                                                     for p in path.split("/")))


def analyze_pull_request_python(repo, number, api=None):
    """Read up to 24 changed Python files at immutable HEAD SHA.

    Never runs code, installs dependencies, follows arbitrary URLs, or accesses
    workspace paths. Missing/oversized/binary/invalid files count as incomplete.
    """
    if not isinstance(repo, str) or not _REPO.fullmatch(repo):
        raise ValueError("Invalid GitHub repository.")
    if isinstance(number, bool) or not str(number).isdigit() or int(number) <= 0:
        raise ValueError("Invalid pull request number.")
    from github_pr_agent import GitHubAPI, APIError
    api = api if api is not None else GitHubAPI()
    pr = api.get(f"/repos/{repo}/pulls/{int(number)}")
    sha = pr.get("head", {}).get("sha", "")
    if not _SHA.fullmatch(sha):
        raise APIError("Pull request head SHA is invalid.")
    declared = int(pr.get("changed_files") or 0)
    files = []
    for page in range(1, 5):
        batch = api.get(f"/repos/{repo}/pulls/{int(number)}/files?per_page=100&page={page}")
        if not isinstance(batch, list) or len(batch) > 100:
            raise APIError("Invalid GitHub files response.")
        files.extend(batch)
        if len(batch) < 100 or (declared and len(files) >= declared):
            break
    candidates = [f for f in files if str(f.get("filename", "")).endswith(".py")
                  and f.get("status") != "removed"]
    report = {"files_analyzed": 0, "python_candidates": len(candidates),
              "unavailable_files": max(0, len(candidates) - _MAX_FILES),
              "parse_failures": 0, "findings": [], "complete": True}
    for item in candidates[:_MAX_FILES]:
        path = item.get("filename")
        patch = item.get("patch")
        if not _safe_path(path) or not isinstance(patch, str) or not patch.strip() \
                or len(patch) > _MAX_PATCH_BYTES:
            report["unavailable_files"] += 1
            continue
        line_numbers = changed_python_lines(patch)
        if not line_numbers:
            report["unavailable_files"] += 1
            continue
        try:
            content = api.get(f"/repos/{repo}/contents/{quote(path, safe='/')}?ref={sha}")
            if (not isinstance(content, dict) or content.get("encoding") != "base64"
                    or not isinstance(content.get("content"), str)
                    or int(content.get("size") or 0) > _MAX_BYTES):
                report["unavailable_files"] += 1
                continue
            payload = base64.b64decode("".join(content["content"].split()), validate=True)
            if len(payload) > _MAX_BYTES:
                report["unavailable_files"] += 1
                continue
            source = payload.decode("utf-8")
            hits = analyze_python_source(source, path, line_numbers)
        except SyntaxError:
            report["parse_failures"] += 1
            continue
        except (APIError, OSError, ValueError, TypeError, UnicodeError, binascii.Error):
            report["unavailable_files"] += 1
            continue
        report["files_analyzed"] += 1
        report["findings"].extend(hits)
    report["findings"] = report["findings"][:60]
    report["complete"] = (report["unavailable_files"] == 0
                          and report["parse_failures"] == 0
                          and declared <= len(files)
                          and not (declared == 0 and len(files) == 400))
    report["warning"] = ("AST heuristics are not verified vulnerabilities; Python files "
                         "are never executed and source is not sent to the LLM.")
    return report
