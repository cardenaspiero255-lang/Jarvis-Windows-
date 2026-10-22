"""Adversarial evidence for model format, AST policy, no-op and availability."""
import unittest
from unittest.mock import Mock
from repository_review_sessions import RepositoryReviewSessions, ReviewDenied
from repository_review_api import RepositoryReviewAPI
from test_repository_review_sessions import archive


class ProposalFailureStageTests(unittest.TestCase):
    def setUp(self):
        self.svc = RepositoryReviewSessions()
        self.sid = self.svc.inspect("owner", archive())["session_id"]

    def test_rejections_have_stable_nonsecret_classification(self):
        cases = (
            ('not JSON at all', 'JSON_FORMAT'),
            ('{"replacement":"return __import__(\'os\').system(\'id\')"}', 'AST_POLICY'),
            ('{"replacement":"return price - qty"}', 'NO_MATERIAL_CHANGE'),
        )
        for reply, reason in cases:
            with self.subTest(reason=reason), self.assertRaises(ReviewDenied) as caught:
                self.svc.propose("owner", self.sid, "src/calc.py", "total",
                                 propose=lambda *_: reply)
            self.assertEqual(caught.exception.reason_code, reason)
            self.assertEqual(self.svc.status("owner", self.sid)["status"], "inspected")
            self.assertNotIn(reply, str(caught.exception))

    def test_unavailable_model_has_distinct_reason(self):
        def absent(*_):
            raise TimeoutError("private source details")
        with self.assertRaises(ReviewDenied) as caught:
            self.svc.propose("owner", self.sid, "src/calc.py", "total", propose=absent)
        self.assertEqual(caught.exception.reason_code, "MODEL_UNAVAILABLE")
        self.assertNotIn("private source", str(caught.exception))

    def test_safe_valid_algebra_reaches_review(self):
        result = self.svc.propose(
            "owner", self.sid, "src/calc.py", "total",
            propose=lambda *_: '{"replacement":"return price * qty"}')
        self.assertEqual(result["status"], "review_required")
        self.assertIn("+    return price * qty", result["diff"])


class NoLeakReviewApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_error_codes_reach_local_api_and_no_raw_model_data(self):
        api = RepositoryReviewAPI()
        events = []
        async def send(evt):
            events.append(evt)
        info = api.sessions.inspect("owner", archive())
        api.proposer = lambda *_: '{"replacement":"return __import__(\'os\').system(\'id\')"}'
        await api.handle({"action": "propose", "session_id": info["session_id"],
                          "path": "src/calc.py", "function": "total",
                          "consent": True}, owner="owner", local=True, send=send)
        self.assertEqual(events[-1]["status"], "denied")
        self.assertEqual(events[-1]["reason_code"], "AST_POLICY")
        self.assertNotIn("__import__", repr(events[-1]))
        self.assertEqual(events[-1]["session_id"], info["session_id"])


if __name__ == "__main__":
    unittest.main()
