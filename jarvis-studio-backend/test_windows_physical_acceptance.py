"""Adversarial validation for physical Windows field-acceptance receipts."""
import copy
import unittest

from physical_windows_acceptance import REQUIRED_CASES, evaluate


def valid_receipt():
    return {
        "schema": "jarvis-windows-physical-v1",
        "platform": "windows",
        "host_type": "physical_observed",
        "source": "interactive_operator",
        "gui_process_observed": True,
        "audio_adapter_detected": True,
        "gui_exe_sha256": "a" * 64,
        "cases": [{"id": case, "outcome": "pass", "evidence_mode": "human_observed"}
                  for case in REQUIRED_CASES],
    }


class PhysicalWindowsAcceptanceTests(unittest.TestCase):
    def test_complete_operator_evidence_is_only_user_attested(self):
        report = evaluate(valid_receipt())
        self.assertEqual(report["status"], "USER_ATTESTED_PHYSICAL")
        self.assertFalse(report["independently_certified"])
        self.assertFalse(report["physical_certified"])
        self.assertEqual(report["blockers"], [])

    def test_missing_or_skipped_microphone_case_blocks_certification(self):
        for invalid in ("skip", "fail"):
            with self.subTest(invalid=invalid):
                receipt = valid_receipt()
                receipt["cases"][0]["outcome"] = invalid
                report = evaluate(receipt)
                self.assertEqual(report["status"], "NOT_CERTIFIED")
                self.assertIn("case:" + receipt["cases"][0]["id"], report["blockers"])

    def test_duplicate_and_unrecognized_case_ids_are_rejected(self):
        receipt = valid_receipt()
        receipt["cases"].append(copy.deepcopy(receipt["cases"][0]))
        self.assertIn("case_inventory", evaluate(receipt)["blockers"])
        receipt = valid_receipt()
        receipt["cases"][0]["id"] = "invented_success"
        self.assertIn("case_inventory", evaluate(receipt)["blockers"])

    def test_ci_virtual_and_unauthenticated_evidence_cannot_be_physical(self):
        for key, bad in (("source", "github_ci"), ("host_type", "virtual"),
                         ("platform", "linux"), ("gui_process_observed", False),
                         ("audio_adapter_detected", False)):
            with self.subTest(key=key):
                receipt = valid_receipt()
                receipt[key] = bad
                self.assertEqual(evaluate(receipt)["status"], "NOT_CERTIFIED")

    def test_missing_invalid_binary_hash_rejected(self):
        for value in ("", "fake", "0"*63, "g"*64):
            receipt = valid_receipt()
            receipt["gui_exe_sha256"] = value
            self.assertIn("gui_exe_sha256", evaluate(receipt)["blockers"])

    def test_synthetic_case_claim_is_rejected_even_when_marked_pass(self):
        receipt = valid_receipt()
        receipt["cases"][0]["evidence_mode"] = "simulated"
        self.assertEqual(evaluate(receipt)["status"], "NOT_CERTIFIED")
        self.assertIn("case:" + receipt["cases"][0]["id"], evaluate(receipt)["blockers"])

    def test_blank_or_unusable_receipt_fails_closed(self):
        for bad in (None, {}, "OK", {"cases": "all green"}):
            with self.subTest(bad=bad):
                self.assertEqual(evaluate(bad)["status"], "NOT_CERTIFIED")

    def test_local_physical_runner_guards_ci_and_never_fakes_audio(self):
        from pathlib import Path
        script = (Path(__file__).resolve().parents[1] /
                  "scripts" / "windows-physical-acceptance.ps1").read_text("utf-8")
        for required in ("Get-CimInstance", "Win32_SoundDevice",
                         "Get-FileHash", "SHA256", "GITHUB_ACTIONS",
                         "Read-Host", "interactive_operator", "human_observed",
                         "independently_certified", "physical_certified"):
            with self.subTest(required=required):
                self.assertIn(required, script)
        self.assertNotIn("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", script)
        self.assertNotIn("Stop-Computer", script)
        self.assertNotIn("Set-ItemProperty", script)


if __name__ == "__main__":
    unittest.main()
