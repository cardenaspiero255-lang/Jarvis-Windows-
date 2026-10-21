"""Windows permission protocol: malformed responses must fail closed."""
import asyncio
import unittest
from unittest import mock

import main


class PermissionProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_truthy_string_cannot_approve_review(self):
        fut = asyncio.get_running_loop().create_future()
        main._pending_perms["token-1"] = fut
        try:
            await main.handle_permission_response({"id": "token-1", "approved": "false"})
            self.assertFalse(fut.done())
            await main.handle_permission_response({"id": "token-1", "approved": True})
            self.assertTrue(fut.result())
        finally:
            main._pending_perms.pop("token-1", None)

    async def test_unrelated_or_malformed_response_never_approves(self):
        fut = asyncio.get_running_loop().create_future()
        main._pending_perms["token-2"] = fut
        try:
            for data in (None, {"id": "another", "approved": True},
                         {"id": "token-2", "approved": 1},
                         {"id": "token-2", "approved": None},
                         {"id": "token-2", "approved": "true"}):
                await main.handle_permission_response(data)
                self.assertFalse(fut.done(), data)
            await main.handle_permission_response({"id": "token-2", "approved": False})
            self.assertFalse(fut.result())
        finally:
            main._pending_perms.pop("token-2", None)

    async def test_request_timeout_denies_and_cleans_up(self):
        main._pending_perms.clear()
        with mock.patch.object(main, "emit", new_callable=mock.AsyncMock) as emit, \
             mock.patch.object(main, "_ask_whatsapp", return_value=None):
            allowed = await main.request_permission("github_pr_read", "review PR 10", timeout=0.005)
        self.assertFalse(allowed)
        self.assertEqual(main._pending_perms, {})
        self.assertEqual(emit.await_args_list[-1].args, ("permission_request", None))

    async def test_two_permissions_get_distinct_unpredictable_ids(self):
        with mock.patch.object(main, "emit", new_callable=mock.AsyncMock) as emit, \
             mock.patch.object(main, "_ask_whatsapp", return_value=None):
            a = asyncio.create_task(main.request_permission("github_pr_read", "PR A", timeout=0.01))
            b = asyncio.create_task(main.request_permission("github_pr_read", "PR B", timeout=0.01))
            await asyncio.gather(a, b)
        ids = [call.args[1]["id"] for call in emit.await_args_list
               if call.args[1] is not None]
        self.assertEqual(len(ids), 2)
        self.assertNotEqual(ids[0], ids[1])
        self.assertTrue(all(len(i) >= 16 for i in ids))


if __name__ == "__main__":
    unittest.main()
