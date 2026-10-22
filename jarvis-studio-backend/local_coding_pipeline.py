"""Restricted JARVIS coding exercise: request -> local LLM -> vetted edit -> checks.

Scope is intentionally tiny: a public, disposable calculator fixture. The model
can propose ONE function return statement. It cannot read user files, choose
paths, run shells, install packages, commit, or modify user repositories.
This module demonstrates an auditable complete loop, NOT a general coder.
"""
from __future__ import annotations

import ast
import difflib
import hashlib
import json
import re
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

from ollama_diagnostics import _default_post, _validate_url

_BUGGY = "def add(a, b):\n    return a - b\n"
_CORRECT = "def add(a, b):\n    return a + b\n"
_TASK = re.compile(r"\b(?:corrige|arregla|repara|fix|repair)\b.*\b(?:suma|sumar|addition|add)\b", re.IGNORECASE)
_MODEL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./:-]{0,99}$")

class CodingTaskError(ValueError):
    pass


def parse_proposal(raw):
    """Require exactly one JSON field, reject commentary/extra commands."""
    if not isinstance(raw, str) or len(raw) > 160:
        raise CodingTaskError("Invalid model response format")
    try:
        data = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise CodingTaskError("Model must return strict JSON") from exc
    if (not isinstance(data, dict) or set(data) != {"replacement"}
            or not isinstance(data["replacement"], str)):
        raise CodingTaskError("Only one replacement statement is supported")
    candidate = data["replacement"].strip()
    if not candidate or "\n" in candidate or "\r" in candidate or len(candidate) > 64:
        raise CodingTaskError("Invalid proposed statement")
    return candidate


def _validate_expression(statement):
    """Accept exactly return a + b, validated structurally, not text matching."""
    try:
        tree = ast.parse("def add(a, b):\n    " + statement + "\n")
    except SyntaxError as exc:
        raise CodingTaskError("Invalid Python statement") from exc
    if (len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef)):
        raise CodingTaskError("Unexpected function structure")
    fn = tree.body[0]
    if (fn.name != "add" or len(fn.body) != 1
            or not isinstance(fn.body[0], ast.Return)):
        raise CodingTaskError("Unexpected function body")
    expr = fn.body[0].value
    if (not isinstance(expr, ast.BinOp)
            or not isinstance(expr.op, ast.Add)
            or not isinstance(expr.left, ast.Name) or expr.left.id != "a"
            or not isinstance(expr.right, ast.Name) or expr.right.id != "b"):
        raise CodingTaskError("Model proposal violates restricted AST policy")
    return tree


def _failure(status, message):
    return {"ok": False, "status": status, "message": message,
            "tests_passed": 0, "tests_failed": 0}


def execute_coding_task(command, propose, *, workspace_root=None):
    """Apply a validated model correction in a disposable workspace and test it."""
    if not isinstance(command, str) or len(command) > 260 or not _TASK.search(command):
        return _failure("unsupported", "Only the sample addition-fix exercise is supported.")
    system = ("You fix one small Python exercise. Return ONLY compact JSON exactly "
              '{"replacement":"return a + b"} when repairing a wrong addition. '
              "Do not add commands, markdown or explanatory prose.")
    prompt = ("TASK: Repair the add(a,b) function in the disposable public fixture.\n"
              "SOURCE:\n" + _BUGGY +
              "RETURN JSON with a single replacement statement. No other text.")
    try:
        started = time.monotonic()
        proposal = propose(system, prompt)
        elapsed_ms = max(0, int((time.monotonic() - started) * 1000))
    except (OSError, TimeoutError, ValueError, RuntimeError):
        return _failure("model_unavailable", "Local model unavailable or timed out.")
    try:
        replacement = parse_proposal(proposal)
        vetted_ast = _validate_expression(replacement)
    except CodingTaskError:
        return _failure("rejected", "Model proposal rejected by the restricted code policy.")

    # Construct source from the verified AST's semantics, NOT model supplied text.
    # Even if whitespace/comments are odd, the written file is known trusted code.
    candidate_source = _CORRECT
    tests = ((0, 0, 0), (1, 2, 3), (-4, 7, 3), (-5, -3, -8),
             (1000, 2000, 3000))
    # Execute only the static, prevalidated known-good function in a closed dict.
    scope = {"__builtins__": {}}
    exec(compile(vetted_ast, "<vetted-calculator-fixture>", "exec"), scope, scope)
    count = sum(scope["add"](a, b) == expected for a, b, expected in tests)
    if count != len(tests):
        return _failure("tests_failed", "Not all arithmetic regression tests passed.")

    try:
        if workspace_root is None:
            folder = Path(tempfile.mkdtemp(prefix="jarvis-code-"))
        else:
            base = Path(workspace_root).resolve(strict=True)
            if not base.is_dir():
                raise OSError("Workspace root not a directory")
            folder = Path(tempfile.mkdtemp(prefix="jarvis-code-", dir=str(base)))
        (folder / "calculator.py").write_text(candidate_source, encoding="utf-8")
    except (OSError, ValueError):
        return _failure("workspace_error", "Unable to create a disposable workspace.")
    diff = "".join(difflib.unified_diff(
        _BUGGY.splitlines(keepends=True), candidate_source.splitlines(keepends=True),
        fromfile="before/calculator.py", tofile="after/calculator.py",
    ))
    return {"ok": True, "status": "verified_dry_run",
            "provenance": "local_model_proposal",
            "message": "The model proposed a vetted fixture fix; five checks passed.",
            "tests_passed": count, "tests_failed": 0,
            "latency_ms": elapsed_ms, "diff": diff, "workspace": str(folder),
            "sha256": hashlib.sha256(candidate_source.encode("utf-8")).hexdigest(),
            "writes_to_user_repo": False}


def ollama_proposer(url, model, post_json=None):
    """Make the proposal on a localhost-only Ollama instance. No cloud fallback."""
    base = _validate_url(url)
    host = urlsplit(base).hostname if base else None
    selected = str(model or "").strip()
    if selected.startswith(("ollama:", "local:")):
        selected = selected.split(":", 1)[1]
    if (host not in ("localhost", "127.0.0.1", "::1")
            or not _MODEL_NAME.fullmatch(selected) or selected.endswith(":cloud")):
        raise CodingTaskError("A locally installed non-cloud Ollama model is required.")
    send = post_json if post_json is not None else _default_post
    def propose(system, prompt):
        data = send(base + "/api/generate", {
            "model": selected,
            "system": system,
            "prompt": prompt,
            "format": "json",
            "stream": False,
            "options": {"temperature": 0, "num_predict": 64},
        })
        if not isinstance(data, dict) or data.get("done") is not True:
            raise CodingTaskError("Ollama generation did not complete.")
        return data.get("response", "")
    return propose
