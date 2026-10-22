"""Bounded read-only ZIP intake and arithmetic-only patch preview for external repositories.

SECURITY: Parses archives and AST, NEVER imports source or executes tests.
No extraction, Git command, network, model call, original file writes or publication.
The caller must obtain explicit permission before previewing source and must
never present the resulting syntax-only preview as an executed regression.
"""
from __future__ import annotations

import ast
import difflib
import hashlib
import io
import os
from pathlib import PurePosixPath
import re
import stat
import zipfile

from controlled_repository_agent import _expression
from local_coding_pipeline import CodingTaskError, parse_proposal

MAX_ARCHIVE = 4 * 1024 * 1024
MAX_ENTRIES = 80
MAX_FILES = 40
MAX_TOTAL = 2 * 1024 * 1024
MAX_FILE = 128 * 1024
MAX_RATIO = 100
EXTENSIONS = {
    ".py": "python", ".js": "javascript", ".jsx": "javascript",
    ".ts": "typescript", ".tsx": "typescript",
    ".kt": "kotlin", ".kts": "kotlin",
    ".md": "documentation", ".json": "json",
}
_RESERVED = re.compile(r"(?i)^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$")


class RepositoryIntakeError(ValueError):
    pass


def _validate_name(name):
    if (not isinstance(name, str) or not name or len(name) > 240
            or name.startswith("/") or "\\" in name or ":" in name
            or "\x00" in name or "%" in name):
        raise RepositoryIntakeError("Unsafe ZIP entry name")
    parts = name.rstrip("/").split("/")
    if (not all(parts) or any(p in (".", "..") or p.startswith(".")
              or p.endswith((" ", ".")) or _RESERVED.fullmatch(p)
              or any(ord(c) < 32 or ord(c) == 127 for c in p)
              for p in parts)):
        raise RepositoryIntakeError("Unsafe ZIP path component")
    return "/".join(parts)


def _read_files(blob):
    if not isinstance(blob, bytes) or not blob or len(blob) > MAX_ARCHIVE:
        raise RepositoryIntakeError("ZIP archive size is invalid")
    files = {}
    canonical_names = set()
    total = 0
    try:
        with zipfile.ZipFile(io.BytesIO(blob), "r", allowZip64=False) as z:
            infos = z.infolist()
            if not infos or len(infos) > MAX_ENTRIES:
                raise RepositoryIntakeError("Too many or no ZIP entries")
            for item in infos:
                name = _validate_name(item.filename)
                folded = name.casefold()
                if folded in canonical_names:
                    raise RepositoryIntakeError("Duplicate or case-colliding ZIP path")
                canonical_names.add(folded)
                mode = item.external_attr >> 16
                ftype = stat.S_IFMT(mode)
                expected_type = stat.S_IFDIR if item.is_dir() else stat.S_IFREG
                if ftype not in (0, expected_type) or item.flag_bits & 1:
                    raise RepositoryIntakeError("Unsupported ZIP member type")
                if item.is_dir():
                    continue
                if PurePosixPath(name).suffix.lower() not in EXTENSIONS:
                    raise RepositoryIntakeError("Executable or unsupported file type")
                if (item.file_size > MAX_FILE or
                        item.file_size > max(item.compress_size, 1) * MAX_RATIO):
                    raise RepositoryIntakeError("Oversized or high-ratio entry")
                total += item.file_size
                if total > MAX_TOTAL or len(files) >= MAX_FILES:
                    raise RepositoryIntakeError("ZIP resource limits exceeded")
                # Reading a bounded amount also defends against deceptive ZIP metadata.
                with z.open(item, "r") as entry:
                    content = entry.read(MAX_FILE + 1)
                    if len(content) != item.file_size or entry.read(1):
                        raise RepositoryIntakeError("ZIP content length mismatch")
                # No binary content or encoding tricks in source previews.
                try:
                    content.decode("utf-8", "strict")
                except UnicodeDecodeError as exc:
                    raise RepositoryIntakeError("Only UTF-8 files are accepted") from exc
                files[name] = content
            # Refuse directory/file prefix collisions, even if differently cased.
            regular = {p.casefold() for p in files}
            for name in files:
                components = name.casefold().split("/")
                for idx in range(1, len(components)):
                    if "/".join(components[:idx]) in regular:
                        raise RepositoryIntakeError("File is also a parent directory")
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile, EOFError, RuntimeError) as exc:
        raise RepositoryIntakeError("Invalid or corrupted ZIP archive") from exc
    if not files:
        raise RepositoryIntakeError("No accepted regular files")
    return files


def inspect_archive(archive):
    """Metadata only; no raw source or source text in returned summary."""
    files = _read_files(archive)
    languages = sorted({EXTENSIONS[PurePosixPath(p).suffix.lower()] for p in files})
    syntax_error_files = 0
    for path, content in files.items():
        if path.endswith(".py"):
            try:
                ast.parse(content.decode("utf-8"), filename="<repository-preview>")
            except (SyntaxError, ValueError):
                syntax_error_files += 1
    return {
        "status": "preview_only",
        "archive_sha256": hashlib.sha256(archive).hexdigest(),
        "file_count": len(files),
        "languages": languages,
        "syntax_error_files": syntax_error_files,
        "execution_allowed": False,
        "modified_user_repo": False,
        "published": False,
    }


def preview_arithmetic_patch(archive, path, function, proposal, *, approved=False):
    """Review-only: apply restricted model return expression to bytes in memory.

    No external tests are run, even if the patch parses. This cannot modify
    an existing repository or grant permission for any other action.
    """
    if approved is not True:
        raise RepositoryIntakeError("Explicit source-inspection permission required")
    if not isinstance(path, str) or _validate_name(path) != path or not path.endswith(".py"):
        raise RepositoryIntakeError("Only explicit Python source paths are supported")
    if not isinstance(function, str) or not function.isidentifier():
        raise RepositoryIntakeError("Invalid function name")
    files = _read_files(archive)
    if path not in files:
        raise RepositoryIntakeError("Target Python file not in archive")
    original = files[path]
    try:
        source = original.decode("utf-8", "strict")
        tree = ast.parse(source)
    except (UnicodeError, SyntaxError, ValueError) as exc:
        raise RepositoryIntakeError("Cannot patch invalid Python source") from exc
    candidates = [node for node in tree.body
                  if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                  and node.name == function]
    if len(candidates) != 1 or not isinstance(candidates[0], ast.FunctionDef):
        raise RepositoryIntakeError("Expected exactly one synchronous top-level function")
    fn = candidates[0]
    args = fn.args
    if (fn.decorator_list or args.posonlyargs or args.kwonlyargs or args.defaults
            or args.kw_defaults or args.vararg or args.kwarg
            or len(args.args) != 2 or len(fn.body) != 1
            or not isinstance(fn.body[0], ast.Return)
            or fn.body[0].lineno != fn.body[0].end_lineno
            or any(not a.arg.isidentifier() for a in args.args)):
        raise RepositoryIntakeError("Function is outside the restricted patch contract")
    try:
        statement = parse_proposal(proposal)
        expression = _expression(statement, tuple(a.arg for a in args.args))
    except CodingTaskError as exc:
        raise RepositoryIntakeError("Unsafe or malformed model proposal") from exc
    lines = source.splitlines(keepends=True)
    line_no = fn.body[0].lineno - 1
    old = lines[line_no]
    match = re.match(r"^([ \t]+)return\b", old)
    if not match or not old.endswith("\n"):
        raise RepositoryIntakeError("Unexpected return statement format")
    # Never copy raw model text: reconstruct only the restricted expression AST.
    lines[line_no] = match.group(1) + "return " + ast.unparse(expression) + "\n"
    patched = "".join(lines).encode("utf-8")
    try:
        ast.parse(patched.decode("utf-8"))
    except (SyntaxError, ValueError) as exc:
        raise RepositoryIntakeError("Patched source is not syntactically valid") from exc
    diff = "".join(difflib.unified_diff(
        source.splitlines(keepends=True),
        patched.decode("utf-8").splitlines(keepends=True),
        fromfile="before/" + path, tofile="after/" + path))
    if not diff:
        raise RepositoryIntakeError("No material change to preview")
    return {
        "status": "preview_only",
        "archive_sha256": hashlib.sha256(archive).hexdigest(),
        "original_sha256": hashlib.sha256(original).hexdigest(),
        "patched_sha256": hashlib.sha256(patched).hexdigest(),
        "modified_files": [path],
        "diff": diff,
        "execution_allowed": False,
        "modified_user_repo": False,
        "published": False,
        "verification": "ast_syntax_only_no_external_tests",
    }
