"""Release publication is only possible from an explicit tag push.

A manual run from a tag is a dry-run installer, not a release publication.
"""
import re
import unittest
from pathlib import Path


class ReleasePublicationGateTests(unittest.TestCase):
    def test_auto_publication_must_verify_trusted_authenticode_before_release(self):
        root = Path(__file__).resolve().parent.parent
        source = (root / ".github" / "workflows" / "release.yml").read_text("utf-8")
        script = (root / "scripts" / "verify-release-signature.ps1").read_text("utf-8")
        self.assertIn("verify-release-signature.ps1", source)
        self.assertLess(source.index("verify-release-signature.ps1"),
                        source.index("name: Publish the release"))
        self.assertIn("Get-AuthenticodeSignature", script)
        self.assertIn("Valid", script)
        self.assertIn("Get-FileHash", script)
        self.assertIn("SHA256", script)
        self.assertIn("ExpectedThumbprint", script)
        self.assertIn("Throw", script)

    def test_release_is_read_only_unless_signed_publication_enabled(self):
        root = Path(__file__).resolve().parent.parent
        source = (root / ".github" / "workflows" / "release.yml").read_text("utf-8")
        self.assertIn("vars.ENABLE_SIGNED_RELEASE", source)
        self.assertIn("secrets.WINDOWS_SIGNING_CERT_THUMBPRINT", source)
        self.assertIn("PUBLISH: ", source)
        # The signed-release gate must be opt-in, and unsigned/tag/manual
        # runs must never be eligible for public publication.
        self.assertRegex(source, r"(?s)- name: Verify pinned Authenticode publisher.*?if: env.PUBLISH == 'true'")
        self.assertRegex(source, r"(?s)ENABLE_SIGNED_RELEASE == 'true'")
        self.assertIn("physical_power_loss_certified = $false", 
                      (root / "scripts" / "verify-release-signature.ps1").read_text("utf-8"))

    def test_packaged_webview_csp_disallows_script_eval(self):
        root = Path(__file__).resolve().parent.parent
        conf = (root / "jarvis-studio-gui" / "src-tauri" /
                "tauri.conf.json").read_text("utf-8")
        import json
        csp = json.loads(conf)["app"]["security"]["csp"]
        self.assertNotIn("'unsafe-eval'", csp)
        self.assertIn("script-src 'self'", csp)

    def test_signed_tag_must_point_to_a_commit_already_merged_into_main(self):
        root = Path(__file__).resolve().parent.parent
        source = (root / ".github" / "workflows" / "release.yml").read_text("utf-8")
        self.assertIn("fetch-depth: 0", source)
        self.assertIn("git merge-base --is-ancestor", source)
        self.assertIn("origin/main", source)
        self.assertLess(source.index("git merge-base --is-ancestor"),
                        source.index("name: Publish the release"))

    def test_manual_dispatch_from_tag_cannot_publish_release(self):
        root = Path(__file__).resolve().parent.parent
        source = (root / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", source)
        match = re.search(r"(?m)^\s+PUBLISH:\s*\$\{\{\s*(.*?)\s*\}\}\s*$", source)
        self.assertIsNotNone(match, "Expected release publication condition")
        condition = match.group(1)
        self.assertIn("github.event_name == 'push'", condition)
        self.assertIn("startsWith(github.ref, 'refs/tags/v')", condition)
        self.assertRegex(source, r"(?s)- name: Publish the release\s+if: env.PUBLISH == 'true'")
        self.assertRegex(source, r"(?s)- name: Keep the dry run's installer\s+if: env.PUBLISH != 'true'")


if __name__ == "__main__":
    unittest.main()
