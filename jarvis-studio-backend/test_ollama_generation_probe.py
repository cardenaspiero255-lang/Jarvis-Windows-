"""Bounded Ollama inference probe and real HTTP Windows transport tests."""
import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ollama_diagnostics import probe_generation


class FakeOllama(BaseHTTPRequestHandler):
    calls = []
    response = {"response": "READY", "done": True}
    def log_message(self, *_args):
        pass
    def do_GET(self):
        self.__class__.calls.append(("GET", self.path, None))
        raw = json.dumps({"models": [{"name": "test-model:latest"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)
    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.__class__.calls.append(("POST", self.path, payload))
        raw = json.dumps(self.__class__.response).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class OllamaProbeTests(unittest.TestCase):
    def test_generates_one_bounded_response_with_model_match(self):
        sent = []
        def post(url, payload):
            sent.append((url, payload))
            return {"response": "READY", "done": True}
        result = probe_generation("http://127.0.0.1:11434", "ollama:my-model",
             get_json=lambda _: {"models": [{"name": "my-model"}]}, post_json=post)
        self.assertTrue(result["ok"])
        self.assertTrue(result["generated"])
        self.assertGreaterEqual(result["latency_ms"], 0)
        self.assertEqual(sent[0][0], "http://127.0.0.1:11434/api/generate")
        self.assertEqual(sent[0][1]["model"], "my-model")
        self.assertFalse(sent[0][1]["stream"])
        self.assertLessEqual(sent[0][1]["options"]["num_predict"], 16)
        self.assertNotIn("READY", str(result))

    def test_unavailable_model_never_generates(self):
        result = probe_generation("http://localhost:11434", "not-installed",
            get_json=lambda _: {"models": [{"name": "other-model"}]},
            post_json=lambda *_: self.fail("must never run generation"))
        self.assertFalse(result["ok"])
        self.assertFalse(result["generated"])

    def test_empty_model_requires_explicit_choice(self):
        result = probe_generation("http://localhost:11434", "",
            get_json=lambda _: {"models": [{"name": "other-model"}]},
            post_json=lambda *_: self.fail("must not choose arbitrary model"))
        self.assertFalse(result["ok"])

    def test_timeout_or_server_error_not_success(self):
        result = probe_generation("http://localhost:11434", "tiny",
            get_json=lambda _: {"models": [{"name": "tiny"}]},
            post_json=lambda *_: (_ for _ in ()).throw(TimeoutError("timeout")))
        self.assertFalse(result["ok"])
        self.assertFalse(result["generated"])
        self.assertNotIn("timeout", str(result).lower().replace("timed out", ""))

    def test_bad_response_or_empty_response_rejected(self):
        for response in ({"done": True, "response": ""},
                         {"response": "READY", "done": False},
                         {"message": {"content": "READY"}},
                         {"response": "READY"}):
            result = probe_generation("http://localhost:11434", "tiny",
                get_json=lambda _: {"models": [{"name": "tiny"}]},
                post_json=lambda *_: response)
            self.assertFalse(result["ok"], response)

    def test_rejects_unencrypted_remote_ollama(self):
        result = probe_generation("http://remote.example:11434", "tiny",
            get_json=lambda _: self.fail("unexpected request"),
            post_json=lambda *_: self.fail("unexpected post"))
        self.assertFalse(result["ok"])

    def test_real_loopback_http_get_and_post(self):
        FakeOllama.calls = []
        FakeOllama.response = {"response": "READY", "done": True}
        server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = probe_generation(f"http://127.0.0.1:{server.server_port}",
                                      "test-model:latest")
            self.assertTrue(result["ok"])
            self.assertTrue(result["generated"])
            self.assertEqual([entry[0] for entry in FakeOllama.calls], ["GET", "POST"])
            self.assertEqual(FakeOllama.calls[-1][1], "/api/generate")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
