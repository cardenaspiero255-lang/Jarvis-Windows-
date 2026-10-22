"""Real loopback WebSocket integration against Windows HUD wire protocol.

No actual physical microphone, Tauri window, model or PC actions involved.
"""
import asyncio
import json
import secrets
import unittest
from unittest.mock import patch

import websockets
from server import websocket_server as wsserver
import main


class LocalPermissionWireTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Real local clients must authenticate with the per-session bearer.
        # Randomize it for each integration test and restore the module state.
        self.local_token = secrets.token_hex(32)
        self.token_override = patch.object(wsserver, "_REQUIRED_TOKEN", self.local_token)
        self.token_override.start()
        self.addCleanup(self.token_override.stop)
        self.previous = wsserver._incoming_handlers.get("permission_response")
        wsserver.register_handler("permission_response", main.handle_permission_response)
        self.server = await websockets.serve(
            wsserver._handler, "127.0.0.1", 0,
            origins=["http://localhost:1420"],
        )
        self.port = self.server.sockets[0].getsockname()[1]
        self.ws = await websockets.connect(
            f"ws://127.0.0.1:{self.port}/?token={self.local_token}",
            origin="http://localhost:1420",
        )

    async def asyncTearDown(self):
        await self.ws.close()
        self.server.close()
        await self.server.wait_closed()
        if self.previous is None:
            wsserver._incoming_handlers.pop("permission_response", None)
        else:
            wsserver.register_handler("permission_response", self.previous)

    async def _request(self, timeout=0.5):
        task = asyncio.create_task(
            main.request_permission("github_pr_read", "read PR metadata", timeout=timeout)
        )
        message = json.loads(await asyncio.wait_for(self.ws.recv(), 2))
        self.assertEqual(message["event"], "permission_request")
        self.assertEqual(message["data"]["kind"], "github_pr_read")
        return task, message["data"]["id"]

    async def test_real_websocket_approve_and_result(self):
        task, identifier = await self._request()
        await self.ws.send(json.dumps({
            "type": "permission_response",
            "data": {"id": identifier, "approved": True},
        }))
        self.assertTrue(await asyncio.wait_for(task, 2))
        cleared = json.loads(await asyncio.wait_for(self.ws.recv(), 2))
        self.assertEqual(cleared, {"event": "permission_request", "data": None})

    async def test_malformed_approval_fails_closed_then_denies(self):
        task, identifier = await self._request()
        await self.ws.send(json.dumps({
            "type": "permission_response",
            "data": {"id": identifier, "approved": "false"},
        }))
        await asyncio.sleep(0.06)
        self.assertFalse(task.done())
        await self.ws.send(json.dumps({
            "type": "permission_response",
            "data": {"id": identifier, "approved": False},
        }))
        self.assertFalse(await asyncio.wait_for(task, 2))
        await asyncio.wait_for(self.ws.recv(), 2)

    async def test_timeout_denies_and_clears_hud(self):
        task, _identifier = await self._request(timeout=0.04)
        self.assertFalse(await asyncio.wait_for(task, 2))
        cleared = json.loads(await asyncio.wait_for(self.ws.recv(), 2))
        self.assertEqual(cleared["data"], None)

if __name__ == "__main__":
    unittest.main()
