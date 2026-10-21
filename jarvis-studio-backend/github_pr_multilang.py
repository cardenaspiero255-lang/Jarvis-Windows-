"""Read-only syntax-aware JavaScript, TypeScript and Kotlin PR heuristics.

Not a full compiler or AST. Never executes code or sends raw source to a model.
Files, calls and output are bounded; missing data is always reported.
"""
import base64
import binascii
import re
from urllib.parse import quote
from github_pr_semantic import changed_python_lines, _safe_path, _MAX_BYTES, _MAX_PATCH_BYTES

_MAX_FILES = 12
_MAX_FINDINGS = 60
_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
_REPO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
RULES = {
    "js-shell-exec", "js-dynamic-eval", "js-dynamic-function",
    "js-html-injection", "js-tls-disabled",
    "kotlin-runtime-exec", "kotlin-process-builder", "kotlin-object-input",
}
_JS = [
    ("js-shell-exec", re.compile(r"\b(?:cp|child_process|childProcess)\s*\.\s*(?:exec|execSync)\s*\(")),
    ("js-dynamic-eval", re.compile(r"(?<![\w$.])eval\s*\(")),
    ("js-dynamic-function", re.compile(r"\bnew\s+Function\s*\(")),
    ("js-html-injection", re.compile(r"\.\s*innerHTML\s*=(?!=)")),
    ("js-tls-disabled", re.compile(r"\brejectUnauthorized\s*:\s*false\b")),
]
_KT = [
    ("kotlin-runtime-exec", re.compile(r"\bRuntime\s*\.\s*getRuntime\s*\(\s*\)\s*\.\s*exec\s*\(")),
    ("kotlin-process-builder", re.compile(r"\bProcessBuilder\s*\(")),
    ("kotlin-object-input", re.compile(r"\bObjectInputStream\s*\(")),
]


def _language(path):
    path = str(path).lower()
    if path.endswith((".ts", ".tsx", ".mts", ".cts")):
        return "typescript"
    if path.endswith((".js", ".jsx", ".mjs", ".cjs")):
        return "javascript"
    if path.endswith((".kt", ".kts")):
        return "kotlin"
    return ""


def _mask_noncode(source, kotlin=False):
    """Blank comments and strings while retaining offsets and newlines.

    JS template interpolation is deliberately masked (may cause false negatives).
    This is NOT a parser or a substitute for professional SAST.
    """
    out = list(source)
    size, pos, state = len(source), 0, "code"
    def blank(lo, hi):
        for at in range(lo, min(hi, size)):
            if out[at] not in ("\n", "\r"):
                out[at] = " "
    while pos < size:
        if state == "code":
            if source.startswith("//", pos):
                blank(pos, pos + 2); pos += 2; state = "line"; continue
            if source.startswith("/*", pos):
                blank(pos, pos + 2); pos += 2; state = "block"; continue
            if kotlin and source.startswith('"""', pos):
                blank(pos, pos + 3); pos += 3; state = "triple"; continue
            if source[pos] in ("'", '"', chr(96)):
                state = source[pos]
                blank(pos, pos + 1); pos += 1; continue
            pos += 1; continue
        if state == "line":
            if source[pos] == "\n":
                state = "code"
            else:
                blank(pos, pos + 1)
            pos += 1; continue
        if state == "block":
            if source.startswith("*/", pos):
                blank(pos, pos + 2); pos += 2; state = "code"
            else:
                blank(pos, pos + 1); pos += 1
            continue
        if state == "triple":
            if source.startswith('"""', pos):
                blank(pos, pos + 3); pos += 3; state = "code"
            else:
                blank(pos, pos + 1); pos += 1
            continue
        if source[pos] == "\\":
            blank(pos, pos + 2); pos += 2
        elif source[pos] == state:
            blank(pos, pos + 1); pos += 1; state = "code"
        else:
            blank(pos, pos + 1); pos += 1
    return "".join(out)


def analyze_script_source(source, filename, patch=None):
    """Metadata-only lexical indicators on added lines (or whole source)."""
    language = _language(filename)
    if not language:
        return []
    if not isinstance(source, str) or len(source.encode("utf-8")) > _MAX_BYTES:
        raise ValueError("Source exceeds analysis limits.")
    changed = changed_python_lines(patch) if patch is not None else None
    masked = _mask_noncode(source, kotlin=(language == "kotlin"))
    results = []
    for rule, regex in (_KT if language == "kotlin" else _JS):
        for match in regex.finditer(masked):
            line = masked.count("\n", 0, match.start()) + 1
            if changed is not None and line not in changed:
                continue
            results.append({"rule": rule, "line": line, "language": language,
                            "file": filename, "kind": "lexical heuristic"})
            if len(results) >= _MAX_FINDINGS:
                break
    return sorted(results, key=lambda item: (item["line"], item["rule"]))[:_MAX_FINDINGS]


def inspect_multilang_pr(repo, number, api=None):
    """Bounded GitHub GETs at immutable PR HEAD, no remote execution or writes."""
    from github_pr_agent import GitHubAPI, APIError
    if (not isinstance(repo, str) or not _REPO.fullmatch(repo) or
            any(part in (".", "..") for part in repo.split("/"))):
        raise ValueError("Invalid repo")
    if isinstance(number, bool) or not str(number).isdigit() or int(number) < 1:
        raise ValueError("Invalid PR number")
    api = api if api is not None else GitHubAPI()
    pr = api.get(f"/repos/{repo}/pulls/{int(number)}")
    sha = (pr.get("head") or {}).get("sha", "")
    if not isinstance(sha, str) or not _SHA.fullmatch(sha):
        raise APIError("Invalid PR head SHA")
    declared = int(pr.get("changed_files") or 0)
    files = []
    for page in range(1, 5):
        batch = api.get(f"/repos/{repo}/pulls/{int(number)}/files?per_page=100&page={page}")
        if not isinstance(batch, list) or len(batch) > 100:
            raise APIError("Invalid PR-files response")
        files.extend(batch)
        if len(batch) < 100 or (declared and len(files) >= declared):
            break
    candidates = [entry for entry in files if
                  _language(entry.get("filename")) and entry.get("status") != "removed"]
    report = {
        "head_sha": sha, "language_candidates": len(candidates),
        "files_analyzed": 0, "unavailable_files": max(0, len(candidates) - _MAX_FILES),
        "by_language": {"javascript": 0, "typescript": 0, "kotlin": 0},
        "findings": [], "complete": False
    }
    for file in candidates[:_MAX_FILES]:
        path, patch = file.get("filename"), file.get("patch")
        if (not _safe_path(path) or not isinstance(patch, str)
                or not patch.strip() or len(patch.encode("utf-8")) > _MAX_PATCH_BYTES
                or not changed_python_lines(patch)):
            report["unavailable_files"] += 1
            continue
        try:
            item = api.get(f"/repos/{repo}/contents/{quote(path, safe='/')}?ref={sha}")
            if (not isinstance(item, dict) or item.get("encoding") != "base64"
                    or not isinstance(item.get("content"), str)
                    or int(item.get("size") or 0) > _MAX_BYTES):
                report["unavailable_files"] += 1; continue
            raw = base64.b64decode("".join(item["content"].split()), validate=True)
            if len(raw) > _MAX_BYTES:
                report["unavailable_files"] += 1; continue
            findings = analyze_script_source(raw.decode("utf-8"), path, patch=patch)
        except (OSError, APIError, ValueError, TypeError, UnicodeError, binascii.Error):
            report["unavailable_files"] += 1
            continue
        report["files_analyzed"] += 1
        report["by_language"][_language(path)] += 1
        report["findings"].extend(findings)
    report["findings"] = report["findings"][:_MAX_FINDINGS]
    report["complete"] = (report["unavailable_files"] == 0 and
                          declared <= len(files) and
                          not (declared == 0 and len(files) == 400))
    report["warning"] = ("Lexical JS/TS/Kotlin heuristics, not AST or complete SAST. "
                         "No code execution, raw source or commands forwarded.")
    return report
