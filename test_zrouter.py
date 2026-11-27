"""
Unit tests for /mnt/zdata/nvidia/zrouter.py
Run with:  cd /mnt/zdata/nvidia && pytest test_zrouter.py -v
"""

from __future__ import annotations

import json
import os
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler
from typing import ClassVar
from unittest import mock

import zrouter
from zrouter import (
    FreeRouter,
    Key,
    RateLimiter,
    RouterError,
    Settings,
    Stats,
    TTLCache,
    classify,
    has_image,
    make_handler,
    mask,
)


class TestMask(unittest.TestCase):
    def test_mask_long_key(self):
        self.assertEqual(
            mask("nvapi-abcd1234abcd1234abcd1234abcd1234"), "nvapi-abc...1234"
        )

    def test_mask_short_key(self):
        self.assertEqual(mask("short"), "***")
        self.assertEqual(mask("exactly16chars!"), "***")

    def test_mask_empty(self):
        self.assertEqual(mask(""), "***")


class TestRateLimiter(unittest.TestCase):
    def test_wait_does_not_raise(self):
        rl = RateLimiter(10000)
        rl.wait()
        rl.wait()

    def test_rpm_zero_defaults_to_one(self):
        rl = RateLimiter(0)
        self.assertEqual(rl.min_interval, 60.0)


class TestKeyThreadSafety(unittest.TestCase):
    def setUp(self):
        self.k = Key("nvapi-abcd1234abcd1234abcd1234abcd1234")

    def test_label_masking(self):
        self.assertEqual(self.k.label, "nvapi-abc...1234")

    def test_is_ready_initial(self):
        self.assertTrue(self.k.is_ready())

    def test_mark_dead(self):
        self.k.mark_dead()
        self.assertTrue(self.k.dead)
        self.assertFalse(self.k.is_ready())

    def test_bench_delays_readiness(self):
        self.k.bench(10)
        self.assertFalse(self.k.is_ready())
        self.assertTrue(self.k.is_ready(now=time.time() + 11))

    def test_record_ok_and_429(self):
        self.k.record_ok()
        self.k.record_ok()
        self.k.record_429()
        snap = self.k.snapshot()
        self.assertEqual(snap["ok"], 2)
        self.assertEqual(snap["hits_429"], 1)
        self.assertFalse(snap["dead"])

    def test_concurrent_record_ok(self):
        def worker():
            for _ in range(1000):
                self.k.record_ok()

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(self.k.ok, 10000)


class TestTTLCache(unittest.TestCase):
    def test_put_and_get(self):
        c = TTLCache(4, 3600)
        c.put("a", 1)
        self.assertEqual(c.get("a"), 1)

    def test_ttl_expiry(self):
        c = TTLCache(4, 1)
        c.put("a", 1)
        self.assertEqual(c.get("a"), 1)
        time.sleep(1.1)
        self.assertIsNone(c.get("a"))

    def test_lru_eviction(self):
        c = TTLCache(3, 3600)
        c.put("b", 2)
        c.put("c", 3)
        c.put("d", 4)
        c.put("e", 5)
        self.assertIsNone(c.get("b"))  # LRU evicted
        self.assertEqual(c.get("c"), 3)
        self.assertEqual(c.get("d"), 4)
        self.assertEqual(c.get("e"), 5)

    def test_ttl_zero_disables_cache(self):
        c = TTLCache(4, 0)
        c.put("a", 1)
        self.assertIsNone(c.get("a"))

    def test_concurrent_put_get(self):
        c = TTLCache(100, 3600)

        def worker(i):
            for j in range(100):
                c.put(f"k{i}-{j}", j)
                assert c.get(f"k{i}-{j}") == j

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()


class TestStats(unittest.TestCase):
    def test_rec_and_flush(self):
        path = os.path.join(os.path.dirname(__file__), "test_stats_tmp.json")
        if os.path.exists(path):
            os.remove(path)
        try:
            s = Stats(path=path)
            s.rec("m1", "k1", "ok", 1.0)
            s.rec("m1", "k1", "fail")
            s.rec("m1", "k1", "429")
            s.flush()
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data["models"]["m1"]["ok"], 1)
            self.assertEqual(data["models"]["m1"]["fail"], 1)
            self.assertEqual(data["models"]["m1"]["429"], 1)
            self.assertEqual(data["models"]["m1"]["lat_sum"], 1.0)
            self.assertEqual(data["keys"]["k1"]["ok"], 1)
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_rec_invalid_outcome_raises(self):
        s = Stats()
        with self.assertRaises(ValueError):
            s.rec("m1", "k1", "bad_outcome")

    def test_snapshot_is_deep_copy(self):
        s = Stats()
        s.rec("m1", "k1", "ok")
        snap = s.snapshot()
        snap["models"]["m1"]["ok"] = 999
        self.assertEqual(s.data["models"]["m1"]["ok"], 1)

    def test_atomic_save_on_dirty_threshold(self):
        path = os.path.join(os.path.dirname(__file__), "test_stats_dirty.json")
        if os.path.exists(path):
            os.remove(path)
        try:
            s = Stats(path=path)
            s.rec("m1", "k1", "ok")
            # dirty=1 < 20, file should not exist yet
            self.assertFalse(os.path.exists(path))
            for _ in range(19):
                s.rec("m1", "k1", "ok")
            # dirty=20 triggers save
            self.assertTrue(os.path.exists(path))
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_load_corrupt_file_tolerated(self):
        path = os.path.join(os.path.dirname(__file__), "test_stats_corrupt.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{not valid json")
        try:
            s = Stats(path=path)
            self.assertEqual(s.data, {"models": {}, "keys": {}})
        finally:
            if os.path.exists(path):
                os.remove(path)


class TestClassifyAndImages(unittest.TestCase):
    def test_classify_code(self):
        self.assertEqual(
            classify([{"role": "user", "content": "write a regex for emails"}]), "code"
        )
        self.assertEqual(
            classify([{"role": "user", "content": "def foo():\n    pass"}]), "code"
        )

    def test_classify_fast(self):
        self.assertEqual(classify([{"role": "user", "content": "hi"}]), "fast")

    def test_classify_reasoning(self):
        self.assertEqual(
            classify([{"role": "user", "content": "prove that 2 + 2 = 4"}]), "reasoning"
        )
        self.assertEqual(
            classify([{"role": "user", "content": "x" * 4000}]), "reasoning"
        )

    def test_classify_general(self):
        self.assertEqual(
            classify(
                [
                    {
                        "role": "user",
                        "content": "The quick brown fox jumps over the lazy dog. This is a simple sentence about animals and nature. Birds sing in the morning and the sun rises in the east. Nothing technical here at all.",
                    }
                ]
            ),
            "general",
        )

    def test_classify_vision(self):
        self.assertEqual(
            classify(
                [
                    {
                        "role": "user",
                        "content": [{"type": "image_url", "image_url": {"url": "x"}}],
                    }
                ]
            ),
            "vision",
        )

    def test_has_image_true(self):
        self.assertTrue(
            has_image(
                [{"role": "user", "content": [{"type": "image_url", "image_url": {}}]}]
            )
        )

    def test_has_image_false(self):
        self.assertFalse(has_image([{"role": "user", "content": "text only"}]))

    def test_text_of_string(self):
        self.assertEqual(zrouter._text_of("hello"), "hello")

    def test_text_of_list(self):
        self.assertEqual(
            zrouter._text_of(
                [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]
            ),
            "a b",
        )

    def test_text_of_other(self):
        self.assertEqual(zrouter._text_of(123), "")


class TestSettings(unittest.TestCase):
    def test_defaults(self):
        s = Settings()
        self.assertEqual(s.rpm, 35)
        self.assertEqual(s.cache_ttl, 3600)
        self.assertEqual(s.timeout, 90)
        self.assertIn("general", s.routes)

    def test_load_valid_config(self):
        path = os.path.join(os.path.dirname(__file__), "test_cfg.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"routes": {"code": ["glm-4.7"]}, "rpm": 30, "cache_ttl": 600}, f)
        try:
            s = Settings()
            s.load(path)
            self.assertEqual(s.rpm, 30)
            self.assertEqual(s.cache_ttl, 600)
            self.assertIn("glm-4.7", s.routes["code"])
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_load_non_dict_root_raises(self):
        path = os.path.join(os.path.dirname(__file__), "test_cfg_bad.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump([1, 2, 3], f)
        try:
            s = Settings()
            with self.assertRaises(TypeError):
                s.load(path)
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_load_rejects_invalid_routes_without_partial_mutation(self):
        path = os.path.join(os.path.dirname(__file__), "test_cfg_bad_routes.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"rpm": 10, "routes": {"code": "not-a-list"}}, f)
        try:
            settings = Settings()
            original_routes = {
                name: list(patterns) for name, patterns in settings.routes.items()
            }
            with self.assertRaises(ValueError):
                settings.load(path)
            self.assertEqual(settings.rpm, 35)
            self.assertEqual(settings.routes, original_routes)
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_load_rejects_out_of_range_rate_limit(self):
        path = os.path.join(os.path.dirname(__file__), "test_cfg_bad_rpm.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"rpm": 0}, f)
        try:
            settings = Settings()
            with self.assertRaises(ValueError):
                settings.load(path)
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_load_rejects_remote_plaintext_provider_url(self):
        path = os.path.join(os.path.dirname(__file__), "test_cfg_bad_url.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"base_url": "http://provider.example.test/v1"}, f)
        try:
            settings = Settings()
            with self.assertRaises(ValueError):
                settings.load(path)
        finally:
            if os.path.exists(path):
                os.remove(path)


class TestLoadKeys(unittest.TestCase):
    def test_load_keys_from_env(self):
        os.environ["NVIDIA_API_KEYS"] = "key1, key2, key1"
        try:
            keys = zrouter.load_keys(providers_file="/tmp/nonexistent_providers.json")
            self.assertEqual(len(keys), 2)
            self.assertEqual(keys[0].value, "key1")
            self.assertEqual(keys[1].value, "key2")
        finally:
            os.environ.pop("NVIDIA_API_KEYS", None)

    def test_load_keys_empty(self):
        for var in ("NVIDIA_API_KEYS", "NVIDIA_API_KEY"):
            os.environ.pop(var, None)
        keys = zrouter.load_keys(providers_file="/tmp/nonexistent_providers.json")
        self.assertEqual(keys, [])

    def test_load_keys_preserves_provider_base_url(self):
        path = os.path.join(os.path.dirname(__file__), "test_providers.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "providers": {
                        "OpenRouter": {
                            "api_keys": ["sk-or-key1"],
                            "base_url": "https://openrouter.ai/api/v1",
                            "env_var": "",
                        }
                    }
                },
                f,
            )
        try:
            for var in ("NVIDIA_API_KEYS", "NVIDIA_API_KEY"):
                os.environ.pop(var, None)
            keys = zrouter.load_keys(providers_file=path)
            self.assertEqual(len(keys), 1)
            self.assertEqual(keys[0].value, "sk-or-key1")
            self.assertEqual(keys[0].provider, "OpenRouter")
            self.assertEqual(keys[0].base_url, "https://openrouter.ai/api/v1")
        finally:
            if os.path.exists(path):
                os.remove(path)


class TestFreeRouterInit(unittest.TestCase):
    def test_no_keys_raises(self):
        for var in ("NVIDIA_API_KEYS", "NVIDIA_API_KEY"):
            os.environ.pop(var, None)
        with self.assertRaises(RouterError) as ctx:
            FreeRouter(providers_file="/tmp/nonexistent_providers.json")
        self.assertEqual(ctx.exception.status, 401)

    def test_api_keys_param(self):
        r = FreeRouter(api_keys=["k1", "k2", "k1"])
        self.assertEqual(len(r.keys), 2)
        self.assertEqual(r.keys[0].value, "k1")


class TestProbe(unittest.TestCase):
    def setUp(self):
        self.r = FreeRouter.__new__(FreeRouter)
        self.r._local = threading.local()
        self.r.keys = [Key("k1")]
        self.r._available = ["gemma-3-27b"]
        self.r._available_at = time.time()
        self.r.available_ids = mock.Mock(return_value=self.r._available)
        self.r.stats = None

    def test_probe_marks_dead_on_401(self):
        fake_resp = mock.Mock(status_code=401)
        with (
            mock.patch.object(self.r, "_key_order", return_value=self.r.keys),
            mock.patch.object(self.r.s, "post", return_value=fake_resp),
        ):
            res = self.r.probe()
        self.assertEqual(res["gemma-3-27b"][0], 401)
        self.assertTrue(self.r.keys[0].dead)

    def test_probe_marks_dead_on_403(self):
        fake_resp = mock.Mock(status_code=403)
        with (
            mock.patch.object(self.r, "_key_order", return_value=self.r.keys),
            mock.patch.object(self.r.s, "post", return_value=fake_resp),
        ):
            res = self.r.probe()
        self.assertEqual(res["gemma-3-27b"][0], 403)
        self.assertTrue(self.r.keys[0].dead)

    def test_probe_benches_on_429(self):
        fake_resp = mock.Mock(status_code=429)
        with (
            mock.patch.object(self.r, "_key_order", return_value=self.r.keys),
            mock.patch.object(self.r.s, "post", return_value=fake_resp),
        ):
            res = self.r.probe()
        self.assertEqual(res["gemma-3-27b"][0], 429)
        self.assertFalse(self.r.keys[0].is_ready())


class TestPlan(unittest.TestCase):
    def setUp(self):
        self.r = FreeRouter.__new__(FreeRouter)
        self.r.keys = [Key("k1"), Key("k2")]
        self.r._available = [
            "mistral-large-3",
            "deepseek-v3.2",
            "glm-4.7",
            "gemma-3-27b",
        ]
        self.r._available_at = time.time()
        self.r.available_ids = mock.Mock(return_value=self.r._available)

    def test_plan_auto_code(self):
        _cands, label = self.r.plan(
            {
                "messages": [{"role": "user", "content": "write a regex"}],
                "model": "auto",
            }
        )
        self.assertEqual(label, "route:code")
        self.assertTrue(len(_cands) > 0)

    def test_plan_unknown_route_raises(self):
        with self.assertRaises(RouterError) as ctx:
            self.r.plan({"messages": []}, route="nope")
        self.assertEqual(ctx.exception.status, 400)

    def test_plan_no_candidates_raises_404(self):
        with self.assertRaises(RouterError) as ctx:
            self.r.plan(
                {
                    "messages": [{"role": "user", "content": "hi"}],
                    "model": "nonexistent-model-xyz",
                }
            )
        self.assertEqual(ctx.exception.status, 404)

    def test_plan_free_prefix_route(self):
        _cands, label = self.r.plan({"messages": []}, model="free-code")
        self.assertEqual(label, "route:code")

    def test_plan_route_colon(self):
        _cands, label = self.r.plan({"messages": []}, model="route:fast")
        self.assertEqual(label, "route:fast")

    def test_plan_exact_route_name(self):
        _cands, label = self.r.plan({"messages": []}, model="vision")
        self.assertEqual(label, "route:vision")

    def test_allowed_requires_exact_id_or_explicit_glob(self):
        self.r._available = ["gemma-3-27b-preview"]
        self.r.available_ids.return_value = self.r._available
        self.assertEqual(self.r.allowed(["gemma-3-27b"]), [])
        self.assertEqual(
            self.r.allowed(["gemma-3-*"]),
            ["gemma-3-27b-preview"],
        )

    def test_plan_does_not_fall_back_to_unlisted_live_models(self):
        self.r._available = ["paid-model-not-in-routes"]
        self.r.available_ids.return_value = self.r._available
        with self.assertRaises(RouterError) as ctx:
            self.r.plan(
                {"messages": [{"role": "user", "content": "hello"}]},
                route="fast",
            )
        self.assertEqual(ctx.exception.status, 404)

    def test_discovery_never_infers_free_pricing(self):
        catalog = zrouter.ModelsCatalog.discover_from_api(
            ["nvidia/example-new-model"], deny=[]
        )
        model = catalog.get("nvidia/example-new-model")
        self.assertFalse(model["free"])
        self.assertEqual(model["pricing_status"], "unverified")


class TestChatJsonAndChat(unittest.TestCase):
    def setUp(self):
        self.r = FreeRouter.__new__(FreeRouter)
        self.r.keys = [Key("k1")]
        self.r._available = [
            "mistral-large-3",
            "deepseek-v3.2",
            "glm-4.7",
            "gemma-3-27b",
        ]
        self.r._available_at = time.time()
        self.r.available_ids = mock.Mock(return_value=self.r._available)
        self.r.stats = None
        self.r.cache = TTLCache(256, 3600)

    @mock.patch.object(FreeRouter, "_open")
    def test_chat_json_caches(self, mock_open):
        mock_open.return_value = (
            mock.Mock(
                json=mock.Mock(
                    return_value={"choices": [{"message": {"content": "hi"}}]}
                )
            ),
            "m1",
            self.r.keys[0],
            0.0,
        )
        body = {
            "messages": [{"role": "user", "content": "hi"}],
            "model": "auto",
            "temperature": 0,
        }
        self.r.chat_json(body)
        out2 = self.r.chat_json(body)
        self.assertEqual(mock_open.call_count, 1)
        self.assertTrue(out2["cached"])

    @mock.patch.object(FreeRouter, "_open")
    def test_chat_no_choices(self, mock_open):
        mock_open.return_value = (
            mock.Mock(json=mock.Mock(return_value={"choices": []})),
            "m1",
            self.r.keys[0],
            0.0,
        )
        out = self.r.chat([{"role": "user", "content": "hi"}])
        self.assertEqual(out["text"], "")
        self.assertEqual(out["message"], {})


class TestReadBody(unittest.TestCase):
    class FakeHandler:
        def __init__(self, body: bytes, content_length: int | None = None):
            import io as _io

            self.rfile = _io.BytesIO(body)
            self.headers = {}
            if content_length is not None:
                self.headers["Content-Length"] = str(content_length)
            else:
                self.headers["Content-Length"] = str(len(body))

    def test_read_body_valid(self):
        h = self.FakeHandler(
            b'{"model":"m","messages":[{"role":"user","content":"hi"}]}'
        )
        code, _body = zrouter._read_body(h)
        self.assertEqual(code, 200)
        self.assertEqual(_body["model"], "m")

    def test_read_body_invalid_json(self):
        h = self.FakeHandler(b"not json")
        code, _body = zrouter._read_body(h)
        self.assertEqual(code, 400)

    def test_read_body_not_dict(self):
        h = self.FakeHandler(b"[1,2,3]")
        code, _body = zrouter._read_body(h)
        self.assertEqual(code, 400)

    def test_read_body_too_large(self):
        h = self.FakeHandler(b"{}", content_length=zrouter.MAX_REQUEST_BYTES + 1)
        code, _body = zrouter._read_body(h)
        self.assertEqual(code, 413)


class MockNVIDIAServer(BaseHTTPRequestHandler):
    """Mock NVIDIA NIM API server for integration tests."""

    requests: ClassVar[list] = []
    auths: ClassVar[list] = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/v1/models":
            body = json.dumps(
                {"data": [{"id": "gemma-3-27b"}, {"id": "deepseek-v3.2"}]}
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n)
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = {}
        self.__class__.requests.append(payload)
        self.__class__.auths.append(self.headers.get("Authorization", ""))
        body = json.dumps(
            {"choices": [{"message": {"content": "mock-response"}}]}
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class TestProxyServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from http.server import ThreadingHTTPServer

        cls.upstream = ThreadingHTTPServer(("127.0.0.1", 0), MockNVIDIAServer)
        cls.thread = threading.Thread(target=cls.upstream.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.upstream.server_port}/v1"
        MockNVIDIAServer.requests.clear()
        MockNVIDIAServer.auths.clear()

    @classmethod
    def tearDownClass(cls):
        cls.upstream.shutdown()
        cls.upstream.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        os.environ["NVIDIA_API_KEYS"] = "test-key-1234567890abcdef"
        os.environ["NVIDIA_BASE_URL"] = self.base_url
        os.environ["NVIDIA_ROUTER_HOME"] = os.path.join(
            os.path.dirname(__file__), "test_proxy_stats"
        )
        import shutil

        if os.path.exists(os.environ["NVIDIA_ROUTER_HOME"]):
            shutil.rmtree(os.environ["NVIDIA_ROUTER_HOME"])

    def tearDown(self):
        for var in ("NVIDIA_API_KEYS", "NVIDIA_BASE_URL", "NVIDIA_ROUTER_HOME"):
            os.environ.pop(var, None)

    def test_health_endpoint(self):
        router = FreeRouter(
            keys_file=None, providers_file="/tmp/nonexistent_providers.json"
        )
        make_handler(router, token=None)
        # Just verify key_status works
        statuses = router.key_status()
        self.assertEqual(len(statuses), 1)

    def test_router_token_auth(self):
        router = FreeRouter(
            keys_file=None, providers_file="/tmp/nonexistent_providers.json"
        )
        handler = make_handler(router, token="secret-token")
        self.assertIsNotNone(handler)

    def test_stats_endpoint_no_stats(self):
        router = FreeRouter(
            keys_file=None,
            stats=False,
            providers_file="/tmp/nonexistent_providers.json",
        )
        self.assertIsNone(router.stats)


class TestSecurity(unittest.TestCase):
    def test_mask_does_not_reveal_full_key(self):
        key = "nvapi-" + "a" * 50
        masked = mask(key)
        self.assertNotIn(key, masked)
        self.assertIn("...", masked)

    def test_read_body_rejects_oversized(self):
        h = TestReadBody.FakeHandler(
            b"{}", content_length=zrouter.MAX_REQUEST_BYTES + 1
        )
        code, _ = zrouter._read_body(h)
        self.assertEqual(code, 413)

    def test_read_body_rejects_non_dict(self):
        h = TestReadBody.FakeHandler(b'"just a string"')
        code, _ = zrouter._read_body(h)
        self.assertEqual(code, 400)

    def test_plan_rejects_unknown_route(self):
        r = FreeRouter.__new__(FreeRouter)
        r.keys = [Key("k1")]
        r._available = ["gemma-3-27b"]
        r._available_at = time.time()
        r.available_ids = mock.Mock(return_value=r._available)
        with self.assertRaises(RouterError) as ctx:
            r.plan({"messages": []}, route="nonexistent")
        self.assertEqual(ctx.exception.status, 400)

    def test_plan_rejects_paid_model(self):
        r = FreeRouter.__new__(FreeRouter)
        r.keys = [Key("k1")]
        r._available = ["gemma-3-27b"]
        r._available_at = time.time()
        r.available_ids = mock.Mock(return_value=r._available)
        with self.assertRaises(RouterError) as ctx:
            r.plan(
                {
                    "messages": [{"role": "user", "content": "hi"}],
                    "model": "gpt-4-turbo",
                }
            )
        self.assertEqual(ctx.exception.status, 404)


class TestCacheBehavior(unittest.TestCase):
    def test_cache_only_when_temperature_zero(self):
        r = FreeRouter.__new__(FreeRouter)
        r.keys = [Key("k1")]
        r._available = ["gemma-3-27b"]
        r._available_at = time.time()
        r.available_ids = mock.Mock(return_value=r._available)
        r.stats = None
        r.cache = TTLCache(256, 3600)

        with mock.patch.object(FreeRouter, "_open") as mock_open:
            mock_open.return_value = (
                mock.Mock(
                    json=mock.Mock(
                        return_value={"choices": [{"message": {"content": "hi"}}]}
                    )
                ),
                "m1",
                r.keys[0],
                0.0,
            )
            # temperature 0, no tools -> cached
            r.chat_json(
                {
                    "messages": [{"role": "user", "content": "hi"}],
                    "model": "auto",
                    "temperature": 0,
                }
            )
            out2 = r.chat_json(
                {
                    "messages": [{"role": "user", "content": "hi"}],
                    "model": "auto",
                    "temperature": 0,
                }
            )
            self.assertTrue(out2["cached"])
            self.assertEqual(mock_open.call_count, 1)

    def test_cache_not_used_when_temperature_nonzero(self):
        r = FreeRouter.__new__(FreeRouter)
        r.keys = [Key("k1")]
        r._available = ["gemma-3-27b"]
        r._available_at = time.time()
        r.available_ids = mock.Mock(return_value=r._available)
        r.stats = None
        r.cache = TTLCache(256, 3600)

        with mock.patch.object(FreeRouter, "_open") as mock_open:
            mock_open.return_value = (
                mock.Mock(
                    json=mock.Mock(
                        return_value={"choices": [{"message": {"content": "hi"}}]}
                    )
                ),
                "m1",
                r.keys[0],
                0.0,
            )
            r.chat_json(
                {
                    "messages": [{"role": "user", "content": "hi"}],
                    "model": "auto",
                    "temperature": 0.7,
                }
            )
            out2 = r.chat_json(
                {
                    "messages": [{"role": "user", "content": "hi"}],
                    "model": "auto",
                    "temperature": 0.7,
                }
            )
            self.assertFalse(out2["cached"])
            self.assertEqual(mock_open.call_count, 2)


class TestChatStreamErrorHandling(unittest.TestCase):
    """Regression tests for chat_stream error handling and response closure."""

    def setUp(self):
        self.r = FreeRouter.__new__(FreeRouter)
        self.r.keys = [Key("k1")]
        self.r._available = ["gemma-3-27b"]
        self.r._available_at = time.time()
        self.r.available_ids = mock.Mock(return_value=self.r._available)
        self.r.stats = None
        self.r.cache = TTLCache(256, 3600)

    def test_chat_stream_propagates_router_error(self):
        """open_chat_stream failure must propagate RouterError, not UnboundLocalError."""
        with (
            mock.patch.object(
                FreeRouter,
                "open_chat_stream",
                side_effect=RouterError(502, "upstream down"),
            ),
            self.assertRaises(RouterError) as ctx,
        ):
            list(self.r.chat_stream([{"role": "user", "content": "hi"}]))
        self.assertEqual(ctx.exception.status, 502)

    def test_chat_stream_closes_response_on_success(self):
        """The upstream response must be closed after streaming completes."""
        mock_resp = mock.Mock()
        mock_resp.iter_lines.return_value = [
            'data: {"choices":[{"delta":{"content":"hi"}}]}',
            "data: [DONE]",
        ]
        with mock.patch.object(
            FreeRouter,
            "open_chat_stream",
            return_value=(mock_resp, "m1", self.r.keys[0]),
        ):
            result = list(self.r.chat_stream([{"role": "user", "content": "hi"}]))
        self.assertEqual(result, ["hi"])
        mock_resp.close.assert_called_once()

    def test_chat_stream_closes_response_on_iteration_error(self):
        """The upstream response must be closed even if iteration raises."""
        mock_resp = mock.Mock()
        mock_resp.iter_lines.side_effect = RuntimeError("stream broke")
        with (
            mock.patch.object(
                FreeRouter,
                "open_chat_stream",
                return_value=(mock_resp, "m1", self.r.keys[0]),
            ),
            self.assertRaises(RuntimeError),
        ):
            list(self.r.chat_stream([{"role": "user", "content": "hi"}]))
        mock_resp.close.assert_called_once()


class TestAvailableIdsResponseClosure(unittest.TestCase):
    """Regression tests for available_ids response closure."""

    def setUp(self):
        self.r = FreeRouter.__new__(FreeRouter)
        self.r._local = threading.local()
        self.r.keys = [Key("k1")]
        self.r._available = None
        self.r._available_at = 0.0

    def test_available_ids_closes_response_on_success(self):
        mock_resp = mock.Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": [{"id": "gemma-3-27b"}]}
        with (
            mock.patch.object(self.r, "_key_order", return_value=self.r.keys),
            mock.patch.object(self.r.s, "get", return_value=mock_resp),
        ):
            result = self.r.available_ids(refresh=True)
        self.assertEqual(result, ["gemma-3-27b"])
        mock_resp.close.assert_called_once()

    def test_available_ids_closes_response_on_429(self):
        mock_resp = mock.Mock()
        mock_resp.status_code = 429
        with (
            mock.patch.object(self.r, "_key_order", return_value=self.r.keys),
            mock.patch.object(self.r.s, "get", return_value=mock_resp),
            self.assertRaises(RouterError),
        ):
            self.r.available_ids(refresh=True)
        mock_resp.close.assert_called_once()


class TestProbeResponseClosure(unittest.TestCase):
    """Regression tests for probe response closure."""

    def setUp(self):
        self.r = FreeRouter.__new__(FreeRouter)
        self.r._local = threading.local()
        self.r.keys = [Key("k1")]
        self.r._available = ["gemma-3-27b"]
        self.r._available_at = time.time()
        self.r.available_ids = mock.Mock(return_value=self.r._available)
        self.r.stats = None

    def test_probe_closes_response_on_200(self):
        mock_resp = mock.Mock(status_code=200)
        with (
            mock.patch.object(self.r, "_key_order", return_value=self.r.keys),
            mock.patch.object(self.r.s, "post", return_value=mock_resp),
        ):
            self.r.probe()
        mock_resp.close.assert_called_once()

    def test_probe_closes_response_on_401(self):
        mock_resp = mock.Mock(status_code=401)
        with (
            mock.patch.object(self.r, "_key_order", return_value=self.r.keys),
            mock.patch.object(self.r.s, "post", return_value=mock_resp),
        ):
            self.r.probe()
        mock_resp.close.assert_called_once()
        self.assertTrue(self.r.keys[0].dead)


if __name__ == "__main__":
    unittest.main()
