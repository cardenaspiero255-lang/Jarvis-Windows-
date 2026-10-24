"""Local Ollama health checks never execute tools or talk to cloud providers."""
import unittest

from ollama_diagnostics import diagnose


class OllamaDiagnosticTests(unittest.TestCase):
    def test_detects_installed_model(self):
        urls = []
        def get(url):
            urls.append(url)
            return {"models": [{"name": "llama3.2:3b"}, {"name": "qwen2.5:7b"}]}
        r = diagnose("http://localhost:11434/", "ollama:llama3.2:3b", get)
        self.assertTrue(r["ok"])
        self.assertTrue(r["selected_available"])
        self.assertEqual(urls, ["http://localhost:11434/api/tags"])

    def test_missing_selected_model_is_reported_not_silently_assumed(self):
        r = diagnose("http://127.0.0.1:11434", "ollama:nonexistent", lambda _: {
            "models": [{"name": "qwen2.5:7b"}]})
        self.assertTrue(r["reachable"])
        self.assertFalse(r["selected_available"])
        self.assertIn("nonexistent", r["message"])

    def test_service_unreachable_is_not_reported_healthy(self):
        def offline(_):
            raise OSError("Connection refused")
        r = diagnose("http://localhost:11434", "llama3", offline)
        self.assertFalse(r["ok"])
        self.assertFalse(r["reachable"])
        self.assertIn("Ollama", r["message"])

    def test_rejects_remote_insecure_http_and_credentials(self):
        for url in ("http://evil.example:11434", "file:///etc/passwd",
                    "http://u:pass@localhost:11434", "http://localhost:11434/a",
                    "http://localhost:11434?x=1"):
            r = diagnose(url, "", lambda _: self.fail("must not connect"))
            self.assertFalse(r["ok"])

    def test_empty_model_catalog_is_not_healthy(self):
        r = diagnose("http://localhost:11434", "", lambda _: {"models": []})
        self.assertFalse(r["ok"])
        self.assertTrue(r["reachable"])

    def test_invalid_provider_payload_fails_closed(self):
        r = diagnose("http://localhost:11434", "", lambda _: {"models": "oops"})
        self.assertFalse(r["ok"])


if __name__ == "__main__":
    unittest.main()
