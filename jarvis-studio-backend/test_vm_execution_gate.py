"""KVM availability never masquerades as a booted, isolated guest."""
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from vm_execution_gate import (
    VMExecutionBlocked, probe_vm_capability, require_verified_vm,
    write_capability_receipt,
)


class VMExecutionGateTests(unittest.TestCase):
    def test_windows_always_denies_linux_microvm_execution(self):
        report = probe_vm_capability(platform="win32")
        self.assertFalse(report["kvm_available"])
        self.assertFalse(report["guest_boot_verified"])
        self.assertFalse(report["untrusted_execution_allowed"])

    def test_linux_missing_kvm_is_not_certified(self):
        report = probe_vm_capability(platform="linux", kvm_path="/a/never/existing/kvm")
        self.assertFalse(report["untrusted_execution_allowed"])
        self.assertFalse(report["guest_boot_verified"])

    def test_kvm_device_alone_is_not_guest_attestation(self):
        with mock.patch("vm_execution_gate.os.stat",
                        return_value=SimpleNamespace(st_mode=stat.S_IFCHR)), \
             mock.patch("vm_execution_gate.os.access", return_value=True):
            report = probe_vm_capability(platform="linux", kvm_path="/dev/kvm")
        self.assertTrue(report["kvm_available"])
        self.assertFalse(report["guest_boot_verified"])
        self.assertFalse(report["untrusted_execution_allowed"])
        with self.assertRaises(VMExecutionBlocked):
            require_verified_vm(report, user_approved=True)

    def test_caller_forged_capabilities_cannot_unlock_execution(self):
        for approved in (True, False):
            with self.subTest(approved=approved), self.assertRaises(VMExecutionBlocked):
                require_verified_vm(
                    {"kvm_available": True, "guest_boot_verified": True,
                     "untrusted_execution_allowed": True}, user_approved=approved)

    def test_receipt_is_bounded_and_contains_no_secrets(self):
        with tempfile.TemporaryDirectory() as folder:
            receipt = write_capability_receipt(Path(folder) / "kvm.json",
                                               probe_vm_capability(platform="win32"))
            data = json.loads(Path(receipt).read_text(encoding="utf-8"))
            self.assertFalse(data["untrusted_execution_allowed"])
            self.assertNotIn("env", data)
            self.assertNotIn("token", str(data).lower())


if __name__ == "__main__":
    unittest.main()
