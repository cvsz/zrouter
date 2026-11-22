from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from scripts.nim_smoke import load_allowed_model, run_smoke


class TestNvidiaNimSmoke(unittest.TestCase):
    def test_accepts_curated_nvidia_model(self) -> None:
        load_allowed_model("nvidia/nemotron-3.5-bolt-e4b")

    def test_rejects_model_outside_curated_free_allowlist(self) -> None:
        with self.assertRaisesRegex(ValueError, "curated NVIDIA free model"):
            load_allowed_model("not-in-catalog")

    def test_rejects_non_official_endpoint_before_network(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "NVIDIA_API_KEY": "synthetic-test-key",
                "NVIDIA_BASE_URL": "https://example.invalid/v1",
            },
        ):
            with patch("scripts.nim_smoke.requests.Session") as session:
                with self.assertRaisesRegex(ValueError, "official HTTPS NVIDIA"):
                    run_smoke("nvidia/nemotron-3.5-bolt-e4b", timeout=5)
                session.assert_not_called()

    def test_sends_exactly_one_bounded_non_streaming_request(self) -> None:
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "choices": [{"message": {"content": "zrouter-nim-smoke-ok"}}]
        }
        session = Mock()
        session.__enter__ = Mock(return_value=session)
        session.__exit__ = Mock(return_value=None)
        session.post.return_value = response
        with (
            patch.dict(
                "os.environ",
                {
                    "NVIDIA_API_KEY": "synthetic-test-key",
                    "NVIDIA_BASE_URL": "https://integrate.api.nvidia.com/v1",
                },
            ),
            patch("scripts.nim_smoke.requests.Session", return_value=session),
            patch("builtins.print"),
        ):
            run_smoke("nvidia/nemotron-3.5-bolt-e4b", timeout=5)
        session.post.assert_called_once()
        kwargs = session.post.call_args.kwargs
        self.assertEqual(kwargs["timeout"], (5, 5))
        self.assertFalse(kwargs["allow_redirects"])
        self.assertFalse(kwargs["json"]["stream"])


if __name__ == "__main__":
    unittest.main()
