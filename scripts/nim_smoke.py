from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import requests


def load_allowed_model(model_id: str) -> None:
    catalog_path = Path(__file__).resolve().parents[1] / "models.json"
    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("unable to load the checked-in model catalog") from exc

    models = catalog.get("models")
    if not isinstance(models, list):
        raise RuntimeError("model catalog has an invalid schema")
    match = next(
        (
            model
            for model in models
            if isinstance(model, dict) and model.get("id") == model_id
        ),
        None,
    )
    if (
        match is None
        or match.get("provider") != "NVIDIA"
        or match.get("free") is not True
    ):
        raise ValueError(
            "model must be explicitly present in models.json as a curated NVIDIA free model"
        )


def run_smoke(model_id: str, timeout: float) -> None:
    api_key = os.environ.get("NVIDIA_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("NVIDIA_API_KEY is not configured in the workflow secret")

    base_url = os.environ.get(
        "NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"
    ).rstrip("/")
    if not base_url.startswith("https://"):
        raise ValueError("NVIDIA_BASE_URL must use HTTPS")

    load_allowed_model(model_id)
    payload: dict[str, Any] = {
        "model": model_id,
        "messages": [
            {
                "role": "user",
                "content": "Reply with exactly: zrouter-nim-smoke-ok",
            }
        ],
        "max_tokens": 16,
        "temperature": 0,
        "stream": False,
    }
    started = time.monotonic()
    with requests.Session() as session:
        response = session.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=(5, timeout),
            allow_redirects=False,
        )
    elapsed = time.monotonic() - started
    if response.status_code != 200:
        raise RuntimeError(
            f"NVIDIA NIM smoke request failed with HTTP {response.status_code}; response body suppressed"
        )
    try:
        data = response.json()
        choices = data.get("choices")
        content = choices[0]["message"]["content"] if choices else None
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        raise RuntimeError("NVIDIA NIM returned an invalid chat completion payload") from exc
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("NVIDIA NIM returned an empty completion")
    print(f"PASS provider=NVIDIA model={model_id} status=200 latency_seconds={elapsed:.2f}")


def main() -> int:
    parser = argparse.ArgumentParser(description="One-request NVIDIA NIM smoke test.")
    parser.add_argument("--model", required=True)
    parser.add_argument("--timeout", type=float, default=25.0)
    args = parser.parse_args()
    if not 1 <= args.timeout <= 60:
        parser.error("--timeout must be between 1 and 60 seconds")
    try:
        run_smoke(args.model, args.timeout)
    except (RuntimeError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
