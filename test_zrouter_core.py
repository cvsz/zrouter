from __future__ import annotations

import unittest

from zrouter_core import ProviderRegistry, validate_base_url


class TestProviderBaseUrl(unittest.TestCase):
    def test_normalizes_https_url(self):
        self.assertEqual(
            validate_base_url("https://api.example.test/v1/"),
            "https://api.example.test/v1",
        )

    def test_allows_loopback_http(self):
        self.assertEqual(
            validate_base_url("http://127.0.0.1:8000/v1/"),
            "http://127.0.0.1:8000/v1",
        )

    def test_rejects_remote_plaintext_http(self):
        with self.assertRaises(ValueError):
            validate_base_url("http://provider.example.test/v1")

    def test_rejects_embedded_credentials(self):
        with self.assertRaises(ValueError):
            validate_base_url("https://user:secret@example.test/v1")

    def test_rejects_query_and_fragment(self):
        values = (
            "https://example.test/v1?token=x",
            "https://example.test/v1#fragment",
        )
        for value in values:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_base_url(value)

    def test_rejects_invalid_schemes(self):
        for value in ("file:///tmp/provider", "ftp://example.test/v1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_base_url(value)


class TestProviderRegistry(unittest.TestCase):
    def test_parses_provider_keys_and_redacts_listing(self):
        registry = ProviderRegistry.from_config(
            {
                "providers": {
                    "OpenRouter": {
                        "api_keys": [" sk-test ", ""],
                        "base_url": "https://openrouter.ai/api/v1/",
                        "env_var": "OPENROUTER_API_KEYS",
                    }
                }
            },
            "https://integrate.api.nvidia.com/v1",
        )
        self.assertEqual(
            registry.all_keys(),
            [("OpenRouter", "https://openrouter.ai/api/v1", "sk-test")],
        )
        self.assertEqual(registry.list_providers()[0]["key_count"], 1)
        self.assertNotIn("sk-test", str(registry.list_providers()))

    def test_rejects_duplicate_names_case_insensitively(self):
        with self.assertRaises(ValueError):
            ProviderRegistry.from_config(
                {"providers": {"NVIDIA": {}, "nvidia": {}}},
                "https://example.test/v1",
            )

    def test_rejects_invalid_key_and_environment_shapes(self):
        cases = [
            {"api_keys": "not-a-list"},
            {"api_keys": [123]},
            {"env_var": "bad-name"},
        ]
        for config in cases:
            with self.subTest(config=config), self.assertRaises(ValueError):
                ProviderRegistry.from_config(
                    {"providers": {"Example": config}},
                    "https://example.test/v1",
                )


if __name__ == "__main__":
    unittest.main()
