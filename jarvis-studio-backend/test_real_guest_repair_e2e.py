"""Regression tests for real GGUF / VM / approved staging orchestration."""
import unittest
from unittest import mock
from real_guest_repair_e2e import demonstrate
from trusted_repair_workflow import WorkflowBlocked

GOOD = '{"replacement":"return quantity * unit_price"}'


class RealGuestRepairE2ETests(unittest.TestCase):
    def test_review_precedes_guest_execution_and_disposable_git_write(self):
        steps = []
        def execute(plan, *, approved, **kwargs):
            steps.append(("review" if not approved else "apply", kwargs))
            return ({"status": "awaiting_explicit_approval"}
                    if not approved else {
                        "status": "verified_disposable_branch",
                        "source_sha256": plan["source_sha256"],
                        "vm_tests_passed": 7, "local_git_tests_passed": 7,
                        "modified_files": ["src/totals.py"],
                    })
        with mock.patch("real_guest_repair_e2e.execute_trusted_plan",
                        side_effect=execute):
            report = demonstrate("/trusted/guest", "/trusted/vmlinuz",
                                 proposer=lambda *_: GOOD)
        self.assertEqual([stage for stage, _ in steps], ["review", "apply"])
        self.assertEqual(report["model_attempts"], 1)
        self.assertEqual(report["vm_tests_passed"], 7)
        self.assertFalse(report["modified_user_repo"])
        self.assertFalse(report["published"])

    def test_two_invalid_proposals_fail_before_vm_or_git(self):
        with mock.patch("real_guest_repair_e2e.execute_trusted_plan",
                        side_effect=AssertionError("Must not execute anything")):
            with self.assertRaises(WorkflowBlocked):
                demonstrate("/trusted/guest", "/trusted/vmlinuz",
                            proposer=lambda *_: '{"replacement":"return open(1)"}')

    def test_one_rejected_proposal_may_be_retried_once(self):
        responses = iter([
            '{"replacement":"return unit_price - quantity"}', GOOD])
        with mock.patch("real_guest_repair_e2e.execute_trusted_plan",
                        side_effect=[
                            {"status": "awaiting_explicit_approval"},
                            {"status": "verified_disposable_branch",
                             "source_sha256": "a" * 64, "vm_tests_passed": 7,
                             "local_git_tests_passed": 7,
                             "modified_files": ["src/totals.py"]},
                        ]):
            report = demonstrate("/trusted/guest", "/trusted/vmlinuz",
                                 proposer=lambda *_: next(responses))
        self.assertEqual(report["model_attempts"], 2)


if __name__ == "__main__":
    unittest.main()
