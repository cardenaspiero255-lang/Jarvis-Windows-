"""Security audit: an Origin header is not proof of local WebView identity."""
import unittest
from unittest.mock import patch
from server import websocket_server as ws


class NativeWithSpoofedOrigin:
    def __init__(self, origin=None, token=None):
        self.remote_address = ("127.0.0.1", 51019)
        self.request_headers = {}
        if origin is not None:
            self.request_headers["Origin"] = origin
        self.path = "/?token=" + (token or "")


class LocalWebSocketAuthenticationAudit(unittest.TestCase):
    def test_allowed_origin_alone_does_not_authenticate_local_native_client(self):
        with patch.object(ws, "_REQUIRED_TOKEN", "a" * 64):
            for origin in ("tauri://localhost", "http://tauri.localhost",
                           "http://localhost:1420", None):
                with self.subTest(origin=origin):
                    self.assertFalse(ws._authorized(
                        NativeWithSpoofedOrigin(origin=origin, token=None)))

    def test_wrong_token_rejected_even_with_trusted_origin(self):
        with patch.object(ws, "_REQUIRED_TOKEN", "a" * 64):
            self.assertFalse(ws._authorized(NativeWithSpoofedOrigin(
                origin="tauri://localhost", token="b" * 64)))

    def test_valid_token_both_with_origin_and_originless_native(self):
        with patch.object(ws, "_REQUIRED_TOKEN", "a" * 64):
            for origin in ("tauri://localhost", None):
                with self.subTest(origin=origin):
                    self.assertTrue(ws._authorized(NativeWithSpoofedOrigin(
                        origin=origin, token="a" * 64)))

    def test_unconfigured_token_denies_loopback_even_from_gui_origin(self):
        with patch.object(ws, "_REQUIRED_TOKEN", ""):
            self.assertFalse(ws._authorized(NativeWithSpoofedOrigin(
                origin="https://tauri.localhost")))

    def test_cross_origin_rejected_despite_valid_token(self):
        with patch.object(ws, "_REQUIRED_TOKEN", "a" * 64):
            self.assertFalse(ws._authorized(NativeWithSpoofedOrigin(
                origin="https://untrusted.example", token="a" * 64)))


if __name__ == "__main__":
    unittest.main()
