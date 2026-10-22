"""Authenticated local desktop WebSocket protocol for ZIP review."""
import asyncio
import base64
import io
import unittest
import zipfile
from repository_review_api import RepositoryReviewAPI


def zip_b64():
    obj = io.BytesIO()
    with zipfile.ZipFile(obj, "w") as z:
        z.writestr("calc.py", "def total(a, b):\n    return a - b\n")
    return base64.b64encode(obj.getvalue()).decode("ascii")


class RepoReviewApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.api = RepositoryReviewAPI()
        self.events = []
        async def send(d):
            self.events.append(d)
        self.send = send

    async def test_remote_clients_never_enter_review_handler(self):
        await self.api.handle({"action": "inspect", "zip_b64": zip_b64(),
                               "consent": True},
                              owner="remote", local=False, send=self.send)
        self.assertEqual(self.events[-1]["status"], "denied")
        self.assertFalse(self.api.sessions._sessions)

    async def test_explicit_read_consent_and_owner_required(self):
        await self.api.handle({"action": "inspect", "zip_b64": zip_b64()},
                              owner="local-1", local=True, send=self.send)
        self.assertEqual(self.events[-1]["status"], "denied")
        await self.api.handle({"action": "inspect", "zip_b64": zip_b64(),
                               "consent": True}, owner="", local=True, send=self.send)
        self.assertEqual(self.events[-1]["status"], "denied")

    async def test_end_to_end_protocol_requires_hash_bound_second_click(self):
        await self.api.handle({"action": "inspect", "zip_b64": zip_b64(), "consent": True},
                              owner="window-1", local=True, send=self.send)
        info = self.events[-1]
        self.assertEqual(info["status"], "inspected")
        self.api.proposer = lambda *_: '{"replacement":"return b * a"}'
        await self.api.handle({"action": "propose", "session_id": info["session_id"],
                               "path": "calc.py", "function": "total",
                               "consent": True}, owner="window-1", local=True, send=self.send)
        preview = self.events[-1]
        self.assertEqual(preview["status"], "review_required")
        await self.api.handle({"action": "apply_copy", "session_id": info["session_id"],
                               "expected_sha256": preview["patched_sha256"]},
                              owner="window-1", local=True, send=self.send)
        self.assertEqual(self.events[-1]["status"], "denied")
        await self.api.handle({"action": "apply_copy", "session_id": info["session_id"],
                               "expected_sha256": preview["patched_sha256"],
                               "approved": True}, owner="window-1", local=True, send=self.send)
        self.assertEqual(self.events[-1]["status"], "copy_staged")
        await self.api.handle({"action": "export", "session_id": info["session_id"]},
                              owner="window-1", local=True, send=self.send)
        self.assertEqual(self.events[-1]["status"], "copy_staged")
        self.assertIn("zip_b64", self.events[-1])
        await self.api.handle({"action": "rollback", "session_id": info["session_id"]},
                              owner="window-1", local=True, send=self.send)
        self.assertEqual(self.events[-1]["status"], "rolled_back")
        await self.api.handle({"action": "export", "session_id": info["session_id"]},
                              owner="window-1", local=True, send=self.send)
        self.assertEqual(self.events[-1]["status"], "denied")

    async def test_failed_approval_keeps_owned_session_discardable(self):
        await self.api.handle({"action": "inspect", "zip_b64": zip_b64(),
                               "consent": True}, owner="window-1",
                              local=True, send=self.send)
        sid = self.events[-1]["session_id"]
        await self.api.handle({"action": "apply_copy",
                               "session_id": sid, "approved": True,
                               "expected_sha256": "0" * 64},
                              owner="window-1", local=True, send=self.send)
        self.assertEqual(self.events[-1]["status"], "denied")
        self.assertEqual(self.events[-1]["session_id"], sid)
        await self.api.handle({"action": "rollback", "session_id": sid},
                              owner="window-1", local=True, send=self.send)
        self.assertEqual(self.events[-1]["status"], "rolled_back")

    async def test_other_window_cannot_read_or_apply_review(self):
        await self.api.handle({"action": "inspect", "zip_b64": zip_b64(),
                               "consent": True}, owner="window-1", local=True, send=self.send)
        sid = self.events[-1]["session_id"]
        await self.api.handle({"action": "rollback", "session_id": sid},
                              owner="window-2", local=True, send=self.send)
        self.assertEqual(self.events[-1]["status"], "denied")
        self.assertIn(sid, self.api.sessions._sessions)


if __name__ == "__main__":
    unittest.main()
