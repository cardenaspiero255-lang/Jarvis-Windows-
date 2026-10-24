"""Model proposal -> immutable review -> VM proof -> approved disposable Git edit."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from trusted_repair_workflow import plan_trusted_repair, execute_trusted_plan, WorkflowBlocked


MODEL = '{"replacement":"return quantity * unit_price"}'


class TrustedRepairWorkflowTests(unittest.TestCase):
    def test_preparation_does_not_touch_git_or_vm(self):
        with mock.patch("trusted_repair_workflow.run_vm_fixture",
                        side_effect=AssertionError("No VM before approval")), \
             mock.patch("trusted_repair_workflow.repair_controlled_repository",
                        side_effect=AssertionError("No Git before approval")):
            plan = plan_trusted_repair(MODEL)
            result = execute_trusted_plan(plan, approved=False)
        self.assertEqual(result["status"], "awaiting_explicit_approval")
        self.assertEqual(plan["source_sha256"],
                         hashlib.sha256(plan["source"].encode()).hexdigest())
        self.assertFalse(result["modified_user_repo"])
        self.assertFalse(result["published"])

    def test_malicious_plan_cannot_ask_vm_to_execute_arbitrary_code(self):
        plan = plan_trusted_repair(MODEL)
        forged = dict(plan, source="import os\nos.system('id')\n")
        with mock.patch("trusted_repair_workflow.run_vm_fixture",
                        side_effect=AssertionError("No VM for forged plan")):
            with self.assertRaises(WorkflowBlocked):
                execute_trusted_plan(forged, approved=True,
                                     vm_rootfs="/fixture", vm_kernel="/kernel")

    def test_vm_missing_attestation_never_writes_git(self):
        plan = plan_trusted_repair(MODEL)
        with mock.patch("trusted_repair_workflow.run_vm_fixture",
                        return_value={"verified": False}), \
             mock.patch("trusted_repair_workflow.repair_controlled_repository",
                        side_effect=AssertionError("Cannot edit before VM proof")):
            with self.assertRaises(WorkflowBlocked):
                execute_trusted_plan(plan, approved=True,
                                     vm_rootfs="/fixture", vm_kernel="/kernel")

    def test_successful_guest_receipt_allows_only_disposable_local_branch(self):
        plan = plan_trusted_repair(MODEL)
        proof = {
            "verified": True, "status": "trusted_fixture_guest_verified",
            "source_sha256": plan["source_sha256"],
            "guest_tests_passed": 7, "publication": "none",
            "user_repository_modified": False,
            "external_repository_execution_authorized": False,
        }
        git_result = {
            "ok": True, "status": "verified_local_branch",
            "modified_files": ["src/totals.py"],
            "source_sha256": plan["source_sha256"],
            "published": False, "modified_user_repo": False,
            "tests_passed": 7, "branch": "jarvis/demo-offline",
        }
        with mock.patch("trusted_repair_workflow.run_vm_fixture", return_value=proof) as vm, \
             mock.patch("trusted_repair_workflow.repair_controlled_repository",
                        return_value=git_result) as git:
            result = execute_trusted_plan(plan, approved=True,
                                          vm_rootfs="/trusted", vm_kernel="/kernel")
        self.assertEqual(result["status"], "verified_disposable_branch")
        self.assertEqual(result["vm_tests_passed"], 7)
        self.assertFalse(result["published"])
        self.assertFalse(result["modified_user_repo"])
        self.assertEqual(vm.call_args.kwargs["source"], plan["source"].encode())
        self.assertEqual(git.call_args.args[1]("system", "prompt"), MODEL)

    def test_vm_sha_mismatch_rejects_even_success_label(self):
        plan = plan_trusted_repair(MODEL)
        with mock.patch("trusted_repair_workflow.run_vm_fixture",
                        return_value={"verified": True,
                                      "status": "trusted_fixture_guest_verified",
                                      "source_sha256": "0" * 64,
                                      "guest_tests_passed": 7,
                                      "publication": "none",
                                      "user_repository_modified": False,
                                      "external_repository_execution_authorized": False}), \
             mock.patch("trusted_repair_workflow.repair_controlled_repository",
                        side_effect=AssertionError("must not touch git")):
            with self.assertRaises(WorkflowBlocked):
                execute_trusted_plan(plan, approved=True,
                                     vm_rootfs="/trusted", vm_kernel="/kernel")


if __name__ == "__main__":
    unittest.main()
