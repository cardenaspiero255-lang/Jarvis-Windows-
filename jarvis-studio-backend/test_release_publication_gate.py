"""Release publication is only possible from an explicit tag push.

A manual run from a tag is a dry-run installer, not a release publication.
"""
import re
import unittest
from pathlib import Path


class ReleasePublicationGateTests(unittest.TestCase):
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
