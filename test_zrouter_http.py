from __future__ import annotations

import json
import threading
import unittest
from http.server import ThreadingHTTPServer

import requests

import zrouter
import zrouter_contracts
import zrouter_http


class FakeStream:
    def __init__(self):
        self.closed = threading.Event()

    def iter_lines(self):
        yield b"data: [DONE]"

    def close(self):
        self.closed.set()


class FakeRouter:
    def __init__(self):
        self.keys = []
        self.stats = None
        self.stream = FakeStream()

    def key_status(self):
        return [("test-key", "nvidia", "ready", 0, 0)]

    def all_allowed(self):
        return ["model-a"]

    def chat_json(self, body):
        return {
            "json": {"id": "test-response", "choices": []},
            "model": "model-a",
            "key": "test-key",
            "cached": False,
        }

    def open_chat_stream(self, body):
        return self.stream, "model-a", "test-key"

    def embeddings(self, body):
        return {"object": "list", "data": []}


class TestHttpCompatibility(unittest.TestCase):
    def test_router_error_reexport_identity(self):
        self.assertIs(zrouter.RouterError, zrouter_contracts.RouterError)

    def test_request_size_contract(self):
        self.assertEqual(zrouter.MAX_REQUEST_BYTES, zrouter_contracts.MAX_REQUEST_BYTES)
        self.assertEqual(zrouter.MAX_REQUEST_BYTES, 16 * 1024 * 1024)

    def test_http_adapter_exposes_expected_operations(self):
        self.assertTrue(callable(zrouter._read_body))
        self.assertTrue(callable(zrouter.make_handler))
        self.assertTrue(callable(zrouter.serve))
        self.assertTrue(callable(zrouter_http.make_handler))
        self.assertTrue(callable(zrouter_http.serve))


class TestHttpAdapterIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.router = FakeRouter()
        cls.token = "synthetic-test-token"
        handler = zrouter_http.make_handler(
            cls.router, cls.token, {"code": ["model-code"]}
        )
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.server.daemon_threads = True
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def auth_headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    def test_rejects_missing_bearer_token(self):
        response = requests.get(f"{self.base_url}/health", timeout=3)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["message"], "invalid router token")

    def test_health_endpoint_requires_and_accepts_token(self):
        response = requests.get(
            f"{self.base_url}/health", headers=self.auth_headers(), timeout=3
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])

    def test_models_endpoint_uses_explicit_routes_and_allowlist(self):
        response = requests.get(
            f"{self.base_url}/v1/models", headers=self.auth_headers(), timeout=3
        )
        self.assertEqual(response.status_code, 200)
        model_ids = [item["id"] for item in response.json()["data"]]
        self.assertEqual(model_ids, ["auto", "free-code", "model-a"])

    def test_invalid_json_is_rejected_before_router_dispatch(self):
        response = requests.post(
            f"{self.base_url}/v1/chat/completions",
            data="{invalid",
            headers=self.auth_headers(),
            timeout=3,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["message"], "invalid JSON")

    def test_chat_completion_uses_router_and_preserves_model_header(self):
        response = requests.post(
            f"{self.base_url}/v1/chat/completions",
            json={"model": "model-a", "messages": []},
            headers=self.auth_headers(),
            timeout=3,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], "test-response")
        self.assertEqual(response.headers["X-Router-Model"], "model-a")

    def test_stream_response_is_closed_after_consumption(self):
        response = requests.post(
            f"{self.base_url}/v1/chat/completions",
            json={"model": "model-a", "messages": [], "stream": True},
            headers=self.auth_headers(),
            stream=True,
            timeout=3,
        )
        try:
            body = list(response.iter_lines())
        finally:
            response.close()
        self.assertIn(b"data: [DONE]", body)
        self.assertTrue(self.router.stream.closed.wait(timeout=2))


if __name__ == "__main__":
    unittest.main()
