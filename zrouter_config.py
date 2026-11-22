"""Validated runtime and provider configuration for zrouter."""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from typing import Any

from zrouter_core import ProviderRegistry, validate_base_url
from zrouter_runtime import RateLimiter, mask

log = logging.getLogger("nvrouter")


def _resource_path(filename: str) -> str:
    """Resolve a data file path, working both from source and PyInstaller bundles."""
    env_var = {
        "models.json": "NVIDIA_MODELS_CATALOG",
        "provider.json": "NVIDIA_PROVIDERS_FILE",
    }[filename]
    env_val = os.environ.get(env_var)
    if env_val:
        return env_val
    if getattr(sys, "frozen", False):
        # Running as PyInstaller bundle: look next to the executable
        return os.path.join(os.path.dirname(sys.executable), filename)
    # Running from source: look next to this file
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)


DEFAULT_RPM = 35
DEFAULT_CACHE_TTL = 3600
DEFAULT_CACHE_SIZE = 256
DEFAULT_TIMEOUT = 90
DEFAULT_MAX_WAIT = 60
DEFAULT_COOLDOWN_429 = 30
DEFAULT_COOLDOWN_ERR = 60
PAIR_BACKOFF_CAP = 900
RETRY_AFTER_CAP = 300
MODEL_LIST_TTL = 900

DEFAULT_ROUTES: dict[str, list[str]] = {
    "general": [
        "mistral-large-3",
        "deepseek-v3.2",
        "glm-4.7",
        "mistral-small-3.1",
        "gemma-3-27b",
        "z-ai/glm-5.3-flash",
        "poolside/laguna-xs-2.1",
        "stepfun-ai/step-5-preview",
        "google/gemma-4-31b-it",
        "openai/gpt-oss-20b",
        "meta/muse-glimmer-30b",
    ],
    "code": [
        "glm-4.7",
        "minimax-m2.5",
        "deepseek-v3.2",
        "deepseek-v3.1-terminus",
        "seed-oss-36b",
        "z-ai/glm-5.3-flash",
        "deepseek-ai/deepseek-v4.1-flash",
        "minimaxai/minimax-m3.1-flash",
    ],
    "reasoning": [
        "deepseek-v3.2",
        "minimax-m2.5",
        "deepseek-v3.1-terminus",
        "glm-4.7",
        "seed-oss-36b",
        "nvidia/nemotron-3.5-super-vl-120b-a12b",
        "nvidia/nemotron-3.5-lightning-30b-a3b",
        "nvidia/nemotron-3-ultra-550b-a55b",
        "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
        "nvidia/meta/llama-3.2-90b-vision-instruct",
        "nvidia/meta/llama-3.2-11b-vision-instruct",
    ],
    "fast": ["gemma-3n-e4b", "gemma-3n-e2b", "mistral-small-3.1", "gemma-3-27b"],
    "vision": [
        "gemma-3-27b",
        "gemma-3n-e4b",
        "mistral-small-3.1",
        "nvidia/nemotron-3.5-super-vl-120b-a12b",
        "nvidia/meta/llama-3.2-90b-vision-instruct",
        "nvidia/meta/llama-3.2-11b-vision-instruct",
    ],
}
DEFAULT_DENY: list[str] = [
    "embed",
    "guard",
    "safety",
    "pii",
    "rerank",
    "clip",
    "flux",
    "cosmos",
    "voice",
    "esm",
    "dino",
]
DEFAULT_EMBED_ALLOW: list[str] = ["nv-embed"]


class Settings:
    """Runtime configuration with type-validated overrides from JSON config."""

    def __init__(self) -> None:
        self.base_url: str = validate_base_url(
            os.environ.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
        )
        self.routes: dict[str, list[str]] = {
            k: list(v) for k, v in DEFAULT_ROUTES.items()
        }
        self.deny: list[str] = list(DEFAULT_DENY)
        self.embed_allow: list[str] = list(DEFAULT_EMBED_ALLOW)
        self.rpm: int = int(os.environ.get("NVIDIA_RPM", str(DEFAULT_RPM)))
        self.cooldown_429: int = DEFAULT_COOLDOWN_429
        self.cooldown_err: int = DEFAULT_COOLDOWN_ERR
        self.max_wait: int = int(
            os.environ.get("NVIDIA_MAX_WAIT", str(DEFAULT_MAX_WAIT))
        )
        self.timeout: int = int(os.environ.get("NVIDIA_TIMEOUT", str(DEFAULT_TIMEOUT)))
        self.cache_ttl: int = int(
            os.environ.get("NVIDIA_CACHE_TTL", str(DEFAULT_CACHE_TTL))
        )
        self.cache_size: int = int(
            os.environ.get("NVIDIA_CACHE_SIZE", str(DEFAULT_CACHE_SIZE))
        )

    def load(self, path: str) -> None:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise TypeError("config root must be a JSON object")

        updates: dict[str, Any] = {}
        integer_bounds = {
            "rpm": (1, 10_000),
            "cooldown_429": (1, 86_400),
            "cooldown_err": (1, 86_400),
            "max_wait": (0, 3_600),
            "timeout": (1, 600),
            "cache_ttl": (0, 86_400),
            "cache_size": (0, 100_000),
        }
        for key, value in data.items():
            if key == "routes":
                if not isinstance(value, dict):
                    raise ValueError("config 'routes' must be an object")
                routes = {
                    name: list(patterns) for name, patterns in self.routes.items()
                }
                for name, patterns in value.items():
                    if (
                        not isinstance(name, str)
                        or not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", name)
                        or not isinstance(patterns, list)
                        or not patterns
                        or any(
                            not isinstance(pattern, str)
                            or not pattern.strip()
                            or len(pattern) > 256
                            or any(ord(char) < 32 for char in pattern)
                            for pattern in patterns
                        )
                    ):
                        raise ValueError(
                            "each route must have a valid name and non-empty "
                            "string patterns"
                        )
                    routes[name] = [pattern.strip() for pattern in patterns]
                updates["routes"] = routes
            elif key in ("deny", "embed_allow"):
                if not isinstance(value, list) or any(
                    not isinstance(item, str) or not item.strip() for item in value
                ):
                    raise ValueError(
                        f"config '{key}' must be a list of non-empty strings"
                    )
                updates[key] = [item.strip() for item in value]
            elif key in integer_bounds:
                minimum, maximum = integer_bounds[key]
                if (
                    isinstance(value, bool)
                    or not isinstance(value, int)
                    or not minimum <= value <= maximum
                ):
                    raise ValueError(
                        f"config '{key}' must be an integer in [{minimum}, {maximum}]"
                    )
                updates[key] = value
            elif key == "base_url":
                if not isinstance(value, str):
                    raise ValueError("config 'base_url' must be a string")
                updates[key] = validate_base_url(value)
            else:
                log.warning("unknown config key: %s", key)

        for key, value in updates.items():
            setattr(self, key, value)


CFG = Settings()


# --------------------------------------------------------------------------- provider config

PROVIDERS_PATH = _resource_path("provider.json")


class ProviderConfig:
    """Load and query provider configurations (API keys + base URLs) from provider.json."""

    def __init__(self, path: str = PROVIDERS_PATH) -> None:
        self.path = path
        self.providers: dict[str, dict[str, Any]] = {}
        self._by_env: dict[str, str] = {}  # env_var -> provider name
        self._load()

    def _load(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            registry = ProviderRegistry.from_config(data, default_base_url=CFG.base_url)
        except FileNotFoundError:
            return
        except (OSError, ValueError, TypeError) as exc:
            log.error(
                "provider configuration rejected (%s); no file-based providers loaded",
                type(exc).__name__,
            )
            return
        self.providers = registry.as_mapping()
        self._by_env = {
            definition.env_var: definition.name
            for definition in registry.definitions
            if definition.env_var
        }

    def get(self, provider: str) -> dict[str, Any] | None:
        """Return provider config, or None if not listed."""
        return self.providers.get(provider)

    def base_url(self, provider: str) -> str:
        cfg = self.get(provider)
        return str(cfg["base_url"]) if cfg else CFG.base_url

    def api_keys(self, provider: str) -> list[str]:
        cfg = self.get(provider)
        return list(cfg["api_keys"]) if cfg else []

    def all_keys(self) -> list[tuple[str, str, str]]:
        """Return list of (provider, base_url, api_key) for all configured keys."""
        out: list[tuple[str, str, str]] = []
        for provider, cfg in self.providers.items():
            base_url = str(cfg["base_url"])
            for key in cfg["api_keys"]:
                if key.strip():
                    out.append((provider, base_url, key.strip()))
        return out

    def list_providers(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for name, cfg in self.providers.items():
            out.append(
                {
                    "name": name,
                    "base_url": str(cfg["base_url"]),
                    "env_var": str(cfg["env_var"]),
                    "key_count": len(cfg["api_keys"]),
                    "has_keys": any(k.strip() for k in cfg["api_keys"]),
                }
            )
        return sorted(out, key=lambda x: str(x["name"]))


PROVIDERS = ProviderConfig()


class Key:
    """A single API key with thread-safe rate limiting, bench state, and counters."""

    def __init__(
        self,
        value: str,
        provider: str = "NVIDIA",
        base_url: str | None = None,
    ) -> None:
        self.value = value
        self.provider = provider
        self.base_url = base_url or CFG.base_url
        self.limiter = RateLimiter(DEFAULT_RPM)
        self._lock = threading.Lock()
        self.benched_until = 0.0
        self.dead = False
        self.ok = 0
        self.fail = 0
        self.hits_429 = 0

    @property
    def label(self) -> str:
        return mask(self.value)

    def is_ready(self, now: float | None = None) -> bool:
        with self._lock:
            t = now if now is not None else time.time()
            return (not self.dead) and t >= self.benched_until

    def mark_dead(self) -> None:
        with self._lock:
            self.dead = True

    def bench(self, seconds: float) -> None:
        with self._lock:
            self.benched_until = max(self.benched_until, time.time() + seconds)

    def record_ok(self) -> None:
        with self._lock:
            self.ok += 1

    def record_fail(self) -> None:
        with self._lock:
            self.fail += 1

    def record_429(self) -> None:
        with self._lock:
            self.hits_429 += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "label": self.label,
                "provider": self.provider,
                "base_url": self.base_url,
                "dead": self.dead,
                "benched_until": self.benched_until,
                "ok": self.ok,
                "fail": self.fail,
                "hits_429": self.hits_429,
            }


def load_keys(
    keys_file: str | None = None,
    providers_file: str | None = None,
) -> list[Key]:
    """Load and de-duplicate API keys from env, keys file, and provider.json."""
    raw: list[str] = []
    for var in ("NVIDIA_API_KEYS", "NVIDIA_API_KEY"):
        raw += re.split(r"[,\s]+", os.environ.get(var, ""))
    if keys_file:
        with open(keys_file, encoding="utf-8") as f:
            for line in f:
                raw += re.split(r"[,\s]+", line.split("#", 1)[0].strip())

    # Load keys from provider.json (preserving per-provider base URLs)
    providers_cfg = ProviderConfig(providers_file or PROVIDERS_PATH)
    provider_info: dict[str, tuple[str, str]] = {}  # key -> (provider, base_url)
    for provider, base_url, key in providers_cfg.all_keys():
        key = key.strip()
        if key and key not in provider_info:
            provider_info[key] = (provider, base_url or CFG.base_url)
        # Also check the provider's env_var for additional keys
        cfg = providers_cfg.get(provider)
        env_var = str(cfg["env_var"]) if cfg else ""
        if env_var:
            raw += re.split(r"[,\s]+", os.environ.get(env_var, ""))

    deduped = [k.strip() for k in raw if k.strip()]
    keys: list[Key] = []
    seen: set[str] = set()
    for k in deduped:
        if k in seen:
            continue
        seen.add(k)
        if k in provider_info:
            prov, base = provider_info[k]
            keys.append(Key(k, provider=prov, base_url=base))
        else:
            keys.append(Key(k))
    # Include provider-only keys that were not already loaded from env / keys file
    for k, (prov, base) in provider_info.items():
        if k in seen:
            continue
        seen.add(k)
        keys.append(Key(k, provider=prov, base_url=base))
    return keys


# --------------------------------------------------------------------------- stats


# --------------------------------------------------------------------------- cache
