"""Local GUI-only WebSocket facade for external ZIP static review.

The transport owner is supplied by the verified local WebSocket ContextVar, not
by JSON. No remote/phone permission can grant access. No external source tests
or user workspace writes. Python model inference is localhost-only.
"""
from __future__ import annotations

import asyncio
import base64
import binascii

from local_coding_pipeline import ollama_proposer, CodingTaskError
from repository_review_sessions import RepositoryReviewSessions, ReviewDenied


class RepositoryReviewAPI:
    def __init__(self):
        self.sessions = RepositoryReviewSessions()
        self.proposer = None
        self._lock = asyncio.Lock()

    async def handle(self, data, *, owner, local, send):
        if local is not True or not isinstance(owner, str) or not owner:
            await send({"status": "denied", "error": "Local desktop session required"})
            return
        if not isinstance(data, dict):
            await send({"status": "denied", "error": "Invalid review request"})
            return
        action = data.get("action")
        try:
            async with self._lock:
                if action == "inspect":
                    if data.get("consent") is not True:
                        raise ReviewDenied("Explicit archive inspection consent required")
                    encoded = data.get("zip_b64")
                    if (not isinstance(encoded, str) or not 0 < len(encoded) < 5_600_000):
                        raise ReviewDenied("ZIP input is empty or exceeds limit")
                    # Strict encoded bytes; no data: URLs or other authority-bearing strings.
                    try:
                        raw = base64.b64decode(encoded, validate=True)
                    except (ValueError, binascii.Error) as exc:
                        raise ReviewDenied("Invalid base64 archive") from exc
                    result = self.sessions.inspect(owner, raw)
                elif action == "propose":
                    if data.get("consent") is not True:
                        raise ReviewDenied("Local model source inspection consent required")
                    propose = self.proposer
                    if propose is None:
                        propose = ollama_proposer(
                            "http://127.0.0.1:11434", "qwen2.5-coder:0.5b")
                    # Do not block other desktop features while local GGUF is generating.
                    result = await asyncio.to_thread(
                        self.sessions.propose,
                        owner, data.get("session_id"),
                        data.get("path"), data.get("function"), propose=propose)
                elif action == "apply_copy":
                    if data.get("approved") is not True:
                        raise ReviewDenied("Second explicit hash-bound approval required")
                    result = self.sessions.apply_copy(
                        owner, data.get("session_id"),
                        data.get("expected_sha256"), approved=True)
                elif action == "stage_git":
                    if data.get("approved") is not True:
                        raise ReviewDenied("Separate explicit Git branch approval required")
                    # Local desktop chooses an existing, clean Git root; model
                    # output cannot select a folder, branch or Git command.
                    result = await asyncio.to_thread(
                        self.sessions.stage_git, owner, data.get("session_id"),
                        data.get("repo_root"), data.get("expected_sha256"),
                        approved=True)
                elif action == "export":
                    result = self.sessions.export(owner, data.get("session_id"))
                elif action == "rollback":
                    result = self.sessions.rollback(owner, data.get("session_id"))
                elif action == "status":
                    result = self.sessions.status(owner, data.get("session_id"))
                else:
                    raise ReviewDenied("Unsupported repository review action")
        except (ReviewDenied, CodingTaskError, TimeoutError, OSError, ValueError):
            # Return only the session ID already owned by this sender so the
            # desktop can discard a rejected review instead of leaking it until TTL.
            error = {"status": "denied", "error": "Request rejected or local model unavailable"}
            try:
                sid = data.get("session_id")
                self.sessions.status(owner, sid)
                error["session_id"] = sid
            except ReviewDenied:
                pass
            await send(error)
            return
        await send(result)
