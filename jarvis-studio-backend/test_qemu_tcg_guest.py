"""A real QEMU guest must execute exact trusted model-patched fixture bytes."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from qemu_tcg_guest import (
    VMGuestError, build_qemu_argv, verify_serial_receipt,
    stage_vm_guest, run_vm_fixture,
)


PATCH = b"def line_total(unit_price, quantity):\n    return quantity * unit_price\n"
IMAGE = "sha256:" + "a" * 64


class QemuTCGGuestTests(unittest.TestCase):
    def test_command_cannot_expose_host_shares_network_or_kvm(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for path in ("kernel", "guest.cpio.gz"):
                (root / path).write_bytes(b"trusted")
            argv = build_qemu_argv(root / "kernel", root / "guest.cpio.gz")
            self.assertIn("tcg", argv)
            self.assertIn("-nic", argv)
            self.assertIn("none", argv)
            self.assertIn("-no-reboot", argv)
            self.assertNotIn("-enable-kvm", argv)
            self.assertNotIn("-drive", argv)
            self.assertNotIn("-virtfs", argv)
            self.assertNotIn("-netdev", argv)
            self.assertNotIn("-fsdev", argv)
            self.assertNotIn("-virtiofs", " ".join(argv))
            self.assertIn("console=ttyS0", " ".join(argv))

    def test_serial_receipt_requires_genuine_matching_nonce_and_sha(self):
        digest = hashlib.sha256(PATCH).hexdigest()
        output = "Linux version 6\nJARVIS_VM_GUEST:" + "abc123" + ":PASS:" + digest + "\n"
        self.assertTrue(verify_serial_receipt(output, "abc123", digest))
        for bad in (output.replace("abc123", "wrong"), output.replace(digest, "0" * 64),
                    output.replace(":PASS:", ":FAIL:"), "JARVIS_VM_GUEST:abc123:PASS:",
                    output + output):
            with self.subTest(bad=bad[:40]), self.assertRaises(VMGuestError):
                verify_serial_receipt(bad, "abc123", digest)

    def test_guest_stage_requires_validated_fixture_source(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "bin").mkdir()
            (root / "usr").mkdir()
            (root / "usr" / "bin").mkdir()
            (root / "usr" / "bin" / "python3").write_bytes(b"trusted-runtime")
            with self.assertRaises(VMGuestError):
                stage_vm_guest(root, b"print('evil')\n", "testnonce")
            detail = stage_vm_guest(root, PATCH, "testnonce")
            self.assertEqual(detail["source_sha256"], hashlib.sha256(PATCH).hexdigest())
            self.assertEqual((root / "work" / "pricing.py").read_bytes(), PATCH)
            self.assertIn("JARVIS_VM_GUEST", (root / "work" / "guest_tests.py").read_text())

    def test_untrusted_repo_is_not_implicitly_executable(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(VMGuestError):
                run_vm_fixture(
                    rootfs=Path(d), kernel=Path(d) / "missing",
                    source=PATCH, expected_source_sha256="0" * 64)

    def test_timeout_or_absent_guest_receipt_is_never_success(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "vmlinuz").write_bytes(b"trusted")
            (root / "usr").mkdir()
            (root / "bin").mkdir()
            (root / "usr" / "bin").mkdir()
            (root / "usr" / "bin" / "python3").write_bytes(b"trusted")
            (root / "dummy-initrd.cpio.gz").write_bytes(b"fixture")
            with mock.patch("qemu_tcg_guest._pack_cpio",
                            return_value=root / "dummy-initrd.cpio.gz"), \
                 mock.patch("qemu_tcg_guest.launch_guest",
                            return_value=(0, "Linux booted")):
                with self.assertRaises(VMGuestError):
                    run_vm_fixture(
                        rootfs=root, kernel=root / "vmlinuz",
                        source=PATCH,
                        expected_source_sha256=hashlib.sha256(PATCH).hexdigest())


if __name__ == "__main__":
    unittest.main()
