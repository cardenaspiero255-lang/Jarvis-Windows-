"""Adversarial read-only intake and model-patch preview for real repository ZIPs."""
import io
import stat
import unittest
import zipfile

from external_repo_preview import (
    RepositoryIntakeError, inspect_archive, preview_arithmetic_patch,
)


def zipped(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items():
            z.writestr(name, content)
    return stream.getvalue()


GOOD = zipped({
    "src/math.py": "def line_total(price, qty):\n    return price - qty\n",
    "README.md": "# Example project\n",
    "src/app.ts": "export const name = 'demo';\n",
})


class ExternalRepositoryPreviewTests(unittest.TestCase):
    def test_readonly_inventory_accepts_real_multilang_archive(self):
        result = inspect_archive(GOOD)
        self.assertEqual(result["status"], "preview_only")
        self.assertEqual(result["file_count"], 3)
        self.assertIn("python", result["languages"])
        self.assertIn("typescript", result["languages"])
        self.assertEqual(len(result["archive_sha256"]), 64)
        self.assertFalse(result["execution_allowed"])
        self.assertFalse(result["modified_user_repo"])
        self.assertFalse(result["published"])

    def test_rejects_traversal_absolute_drive_backslash_and_metadata(self):
        for filename in ("../oops.py", "/tmp/oops.py", "C:/oops.py",
                         "src/./oops.py", ".git/config",
                         "src/.env", "src/../../oops.py", "CON.py"):
            with self.subTest(filename=filename):
                with self.assertRaises(RepositoryIntakeError):
                    inspect_archive(zipped({filename: "pass\n"}))

    def test_raw_zip_header_backslash_rejected_even_on_windows(self):
        # ZipInfo normalizes \ to / on Windows when *building* the test ZIP.
        # Patch the literal central and local filename headers with same-size
        # raw bytes to exercise the actual untrusted archive input.
        normal = zipped({"src/oops.py": "pass\n"})
        self.assertEqual(normal.count(b"src/oops.py"), 2)
        crafted = normal.replace(b"src/oops.py", b"src\\oops.py")
        with self.assertRaises(RepositoryIntakeError):
            inspect_archive(crafted)

    def test_rejects_case_collisions_and_duplicate_zip_entries(self):
        with self.assertRaises(RepositoryIntakeError):
            inspect_archive(zipped({"src/A.py": "pass\n", "src/a.py": "pass\n"}))
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as z:
            z.writestr("a.py", "pass\n")
            z.writestr("a.py", "pass\n")
        with self.assertRaises(RepositoryIntakeError):
            inspect_archive(stream.getvalue())

    def test_rejects_symlink_and_unsupported_extensions(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as z:
            member = zipfile.ZipInfo("src/link.py")
            member.create_system = 3
            member.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(member, "outside.py")
        with self.assertRaises(RepositoryIntakeError):
            inspect_archive(stream.getvalue())
        with self.assertRaises(RepositoryIntakeError):
            inspect_archive(zipped({"run.sh": "echo secret"}))

    def test_rejects_zip_bomb_and_bad_input(self):
        for data in (b"not-zip", b"", zipped({"x.py": "x" * 300000}),
                     zipped({"x.py": "0" * 160000})):
            with self.subTest(size=len(data)), self.assertRaises(RepositoryIntakeError):
                inspect_archive(data)

    def test_python_syntax_errors_are_metadata_only(self):
        broken = zipped({"bad.py": "def bad(:\n  pass\n"})
        report = inspect_archive(broken)
        self.assertEqual(report["syntax_error_files"], 1)
        self.assertNotIn("def bad(", str(report))
        self.assertFalse(report["execution_allowed"])

    def test_real_checked_in_multimodule_repo_is_previewed_without_execution(self):
        from pathlib import Path
        fixture = Path(__file__).resolve().parent / "fixtures" / "isolation_repo"
        paths = ("README.md", "src/pricing.py", "src/coupons.py",
                 "src/orders.py", "tests/test_checkout.py",
                 "tests/test_isolation.py")
        archive = zipped({path: (fixture / path).read_bytes() for path in paths})
        report = inspect_archive(archive)
        self.assertEqual(report["file_count"], len(paths))
        self.assertEqual(report["syntax_error_files"], 0)
        patch = preview_arithmetic_patch(
            archive, "src/pricing.py", "line_total",
            '{"replacement":"return quantity * unit_price"}', approved=True)
        self.assertIn("quantity * unit_price", patch["diff"])
        self.assertEqual(patch["verification"], "ast_syntax_only_no_external_tests")
        self.assertFalse(patch["execution_allowed"])
        self.assertEqual((fixture / "src/pricing.py").read_bytes().replace(b"\r\n", b"\n"),
                         b"def line_total(unit_price, quantity):\n"
                         b"    return unit_price - quantity\n")

    def test_arithmetic_proposal_requires_explicit_read_consent(self):
        with self.assertRaises(RepositoryIntakeError):
            preview_arithmetic_patch(GOOD, "src/math.py", "line_total",
                                     '{"replacement":"return price * qty"}')

    def test_arithmetic_proposal_is_model_exact_and_memory_only(self):
        result = preview_arithmetic_patch(
            GOOD, "src/math.py", "line_total",
            '{"replacement":"return qty * price"}', approved=True)
        self.assertEqual(result["status"], "preview_only")
        self.assertIn("+    return qty * price", result["diff"])
        self.assertEqual(result["modified_files"], ["src/math.py"])
        self.assertFalse(result["execution_allowed"])
        self.assertFalse(result["modified_user_repo"])
        self.assertFalse(result["published"])
        self.assertNotEqual(result["patched_sha256"], result["original_sha256"])
        self.assertEqual(len(result["patched_sha256"]), 64)

    def test_rejects_unsafe_code_and_out_of_scope_paths(self):
        hostile = (
            '{"replacement":"return __import__(\'os\').system(\'id\')"}',
            '{"replacement":"return price ** qty"}',
            '{"replacement":"return price * qty; print(1)"}',
            '{"replacement":"return random_value"}',
        )
        for proposal in hostile:
            with self.subTest(proposal=proposal), self.assertRaises(RepositoryIntakeError):
                preview_arithmetic_patch(GOOD, "src/math.py", "line_total",
                                         proposal, approved=True)
        for path in ("../src/math.py", "README.md", "src/app.ts", "missing.py"):
            with self.subTest(path=path), self.assertRaises(RepositoryIntakeError):
                preview_arithmetic_patch(GOOD, path, "line_total",
                                         '{"replacement":"return price * qty"}',
                                         approved=True)

    def test_rejects_complex_untrusted_function_without_execution(self):
        source = zipped({"src/math.py": (
            "def line_total(price, qty):\n"
            "    import os\n"
            "    return price * qty\n")})
        with self.assertRaises(RepositoryIntakeError):
            preview_arithmetic_patch(source, "src/math.py", "line_total",
                                     '{"replacement":"return price * qty"}',
                                     approved=True)


if __name__ == "__main__":
    unittest.main()
