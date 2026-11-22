#!/usr/bin/env python3
"""
zrouter.py  -  free-only router for NVIDIA's hosted NIM endpoints
(https://integrate.api.nvidia.com/v1)

Enterprise-grade OpenAI-compatible proxy/router with model allowlisting,
multi-key rotation, per-key rate limiting, exponential backoff, streaming
failover, response caching, persistent stats, and an embedded proxy server.

FEATURES
  * Free-only allowlist (ROUTES). /v1/models does not say what is free, so only
    models matching your allowlist are ever called.
  * Routes: general / code / reasoning / fast / vision + "auto" (classifies prompt).
  * Model fallback chain per route.
  * Multi-key rotation: on 429 the key is benched (Retry-After honoured) and the
    SAME model is retried on the next key; dead keys (401/403) are dropped.
  * Per-key rate limiter, exponential backoff for failing (key, model) pairs,
    optional wait-and-retry when every key is limited.
  * Streaming (SSE) with failover before the first byte.
  * Passthrough of tools / tool_choice / response_format / temperature / images.
  * Embeddings endpoint (allowlist EMBED_ALLOW).
  * Response cache (only for temperature == 0, no tools, non-stream).
  * Persistent stats (per model / per key: ok, fail, 429, latency).
  * Local OpenAI-compatible proxy server -> point ANY OpenAI client at it.
  * JSON config file to override routes / limits.
  * Thread-safe, type-annotated, input-validated, production-hardened.

SETUP
    pip install requests
    export NVIDIA_API_KEYS="nvapi-aaa,nvapi-bbb"     # or NVIDIA_API_KEY, or --keys-file keys.txt

USAGE
    python zrouter.py keys
    python zrouter.py list
    python zrouter.py probe
    python zrouter.py chat "write a regex for emails"            # auto route
    python zrouter.py chat "hi" --route fast --stream
    python zrouter.py stats
    python zrouter.py serve --port 8000                          # OpenAI-compatible proxy
        # client:  base_url=http://127.0.0.1:8000/v1  api_key=anything (or ROUTER_TOKEN)
        # model:   "auto" | "free-code" | "free-reasoning" | "free-fast" | "free-vision" | "glm-4.7" ...

CONFIG (optional router.json, via --config or NVIDIA_ROUTER_CONFIG)
    {"routes": {"code": ["glm-4.7", "deepseek-v3.2"]}, "rpm": 30, "cache_ttl": 600,
     "deny": ["embed", "guard"], "embed_allow": ["nv-embed"], "max_wait": 30}

Use only keys that belong to you / your team.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import hmac
import json
import logging
import os
import re
import sys
import threading
import time
import uuid
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import requests

from zrouter_bot import (
    BotHealth,
    CalendarManager,
    CartManager,
    CloudAgentManager,
    EmailManager,
    FileHandler,
    MediaManager,
    MeetingManager,
    NetworkManager,
    PageManager,
    Routine,
    RoutineScheduler,
    SkillLibrary,
    VaultEntry,
    get_bot,
)
from zrouter_core import ProviderRegistry, validate_base_url
from zrouter_runtime import (
    RateLimiter,
    Stats,
    TTLCache,
    mask,
)

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


# --------------------------------------------------------------------------- constants

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


# --------------------------------------------------------------------------- helpers


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


# --------------------------------------------------------------------------- prompt analysis


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            p.get("text", "")
            for p in content
            if isinstance(p, dict) and p.get("type") == "text"
        )
    return ""


def has_image(messages: list[dict[str, Any]]) -> bool:
    return any(
        isinstance(m.get("content"), list)
        and any(
            isinstance(p, dict) and p.get("type") == "image_url" for p in m["content"]
        )
        for m in messages
    )


CODE_RE = re.compile(
    r"```|\bdef \w+\(|\bclass \w+|function\s*\w*\(|traceback|stack ?trace|\bregex\b|\bsql\b|"
    r"\bpython\b|javascript|typescript|\brust\b|golang|\bbug\b|refactor|compile|\bapi\b|"
    r"dockerfile|bash script|unit test|\bgit\b",
    re.IGNORECASE,
)
REASON_RE = re.compile(
    r"step[- ]by[- ]step|\bprove\b|\bderive\b|\bpuzzle\b|\bmath\b|calculate|probability|"
    r"trade-?offs?|analy[sz]e|reason(ing)? about|logic|optimi[sz]e|\bwhy\b.*\bwork",
    re.IGNORECASE,
)


def classify(messages: list[dict[str, Any]]) -> str:
    if has_image(messages):
        return "vision"
    last = next(
        (
            _text_of(m.get("content"))
            for m in reversed(messages)
            if m.get("role") == "user"
        ),
        "",
    )
    if CODE_RE.search(last):
        return "code"
    if REASON_RE.search(last) or len(last) > 3000:
        return "reasoning"
    if len(last) < 160:
        return "fast"
    return "general"


# --------------------------------------------------------------------------- settings


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


# --------------------------------------------------------------------------- models catalog

MODELS_PATH = _resource_path("models.json")


class ModelsCatalog:
    """Load and query the NVIDIA NIM models catalog (free/paid/provider metadata)."""

    def __init__(self, path: str = MODELS_PATH) -> None:
        self.path = path
        self.models: list[dict[str, Any]] = []
        self.providers: dict[str, str] = {}
        self.deny: list[str] = []
        self._by_id: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        self.models = (
            data.get("models", []) if isinstance(data.get("models"), list) else []
        )
        self.providers = (
            data.get("providers", {}) if isinstance(data.get("providers"), dict) else {}
        )
        self.deny = data.get("deny", []) if isinstance(data.get("deny"), list) else []
        self._by_id = {
            m["id"]: m for m in self.models if isinstance(m, dict) and "id" in m
        }

    def get(self, model_id: str) -> dict[str, Any] | None:
        """Return catalog entry for a model id, or None if not listed."""
        return self._by_id.get(model_id)

    def is_free(self, model_id: str) -> bool:
        entry = self.get(model_id)
        return bool(entry and entry.get("free", False))

    def provider(self, model_id: str) -> str:
        entry = self.get(model_id)
        if entry:
            return str(entry.get("provider", "unknown"))
        return "unknown"

    def routes(self, model_id: str) -> list[str]:
        entry = self.get(model_id)
        return list(entry.get("routes", [])) if entry else []

    def is_denied(self, model_id: str) -> bool:
        low = model_id.lower()
        return any(d in low for d in self.deny)

    def list_free(self) -> list[dict[str, Any]]:
        return [m for m in self.models if m.get("free")]

    def list_paid(self) -> list[dict[str, Any]]:
        return [m for m in self.models if not m.get("free")]

    def by_provider(self, provider: str) -> list[dict[str, Any]]:
        return [m for m in self.models if m.get("provider") == provider]

    # ------------------------------------------------------------------- discovery helpers

    @staticmethod
    def _detect_provider(model_id: str) -> str:
        """Heuristically detect the model provider from its ID."""
        low = model_id.lower()
        if "nemotron" in low or low.startswith("nv-") or "embed" in low:
            return "NVIDIA"
        if "llama" in low:
            return "Meta"
        if "gemma" in low:
            return "Google"
        if "deepseek" in low:
            return "DeepSeek"
        if "glm" in low:
            return "Zhipu AI"
        if "mistral" in low:
            return "Mistral AI"
        if "minimax" in low:
            return "MiniMax"
        if "seed" in low:
            return "Seed"
        return "unknown"

    @staticmethod
    def _detect_routes(model_id: str, deny: list[str] | None = None) -> list[str]:
        """Heuristically assign router routes to a model ID."""
        low = model_id.lower()
        deny = deny or []
        if any(d in low for d in deny):
            return []  # denied models get no chat routes
        routes: list[str] = []
        if "embed" in low:
            routes.append("embed")
        if any(
            k in low for k in ("code", "coder", "deepseek", "glm", "minimax", "seed")
        ):
            routes.append("code")
        if any(
            k in low
            for k in (
                "reasoning",
                "nemotron",
                "llama",
                "deepseek",
                "glm",
                "seed",
                "mistral-large",
            )
        ):
            routes.append("reasoning")
        if any(k in low for k in ("mini", "small", "8b", "4b", "2b", "n-e2b", "n-e4b")):
            routes.append("fast")
        if any(k in low for k in ("vision", "vl", "multimodal", "image")):
            routes.append("vision")
        if not routes:
            routes.append("general")
        return routes

    @staticmethod
    def _is_free(
        model_id: str, routes: list[str], deny: list[str] | None = None
    ) -> bool:
        """Never infer pricing from a model ID or route classification."""
        _ = (model_id, routes, deny)
        return False

    @classmethod
    def discover_from_api(
        cls,
        model_ids: list[str],
        deny: list[str] | None = None,
        providers: dict[str, str] | None = None,
    ) -> ModelsCatalog:
        """Classify a list of model IDs (from the NVIDIA API) into a catalog."""
        deny = deny or []
        providers = providers or {}
        models: list[dict[str, Any]] = []
        for mid in sorted(set(model_ids)):
            routes = cls._detect_routes(mid, deny)
            models.append(
                {
                    "id": mid,
                    "provider": providers.get(mid, cls._detect_provider(mid)),
                    "free": False,
                    "pricing_status": "unverified",
                    "routes": routes,
                    "description": f"Auto-discovered {mid}",
                }
            )
        cat = cls.__new__(cls)
        cat.path = MODELS_PATH
        cat.models = models
        cat.providers = dict(providers)
        cat.deny = list(deny)
        cat._by_id = {m["id"]: m for m in models}
        return cat

    def update_from_router(self, router: FreeRouter) -> int:
        """Fetch the live model list from the NVIDIA API and merge into this catalog."""
        try:
            live = router.available_ids(refresh=True)
        except RouterError:
            return 0
        if not live:
            return 0
        discovered = self.discover_from_api(
            live, deny=self.deny, providers=self.providers
        )
        # Preserve descriptions for known models; set new ones
        for m in discovered.models:
            existing = self._by_id.get(m["id"])
            if existing:
                if existing.get("description"):
                    m["description"] = existing["description"]
                m["free"] = existing.get("free") is True
                m["pricing_status"] = existing.get(
                    "pricing_status",
                    "curated" if existing.get("free") is True else "unverified",
                )
        self.models = discovered.models
        self._by_id = discovered._by_id
        return len(self.models)

    def save(self, path: str | None = None) -> None:
        """Persist the catalog to models.json."""
        target = path or self.path
        data: dict[str, Any] = {
            "models": self.models,
            "providers": self.providers,
            "deny": self.deny,
        }
        tmp = target + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, target)


CATALOG = ModelsCatalog()


# --------------------------------------------------------------------------- router


class FreeRouter:
    """Thread-safe router that fans out to NVIDIA NIM endpoints with fallback, rate limiting,
    key rotation, caching, and persistent stats."""

    def __init__(
        self,
        api_keys: list[str] | None = None,
        keys_file: str | None = None,
        providers_file: str | None = None,
        stats: bool = True,
    ) -> None:
        self.keys: list[Key] = (
            [Key(k) for k in dict.fromkeys(api_keys)]
            if api_keys
            else load_keys(keys_file, providers_file)
        )
        if not self.keys:
            raise RouterError(
                401,
                "No API key. Set NVIDIA_API_KEY / NVIDIA_API_KEYS or --keys-file "
                "(free keys at build.nvidia.com).",
            )
        # Re-key limiters to the configured RPM after Key construction
        for k in self.keys:
            k.limiter = RateLimiter(CFG.rpm)
        self._local = threading.local()
        self.pair: dict[
            tuple[str, str], list[float]
        ] = {}  # (key, model) -> [benched_until, consecutive_fails]
        self._rr = 0
        self._lock = threading.Lock()
        self._available: list[str] | None = None
        self._available_at = 0.0
        self.cache = TTLCache(CFG.cache_size, CFG.cache_ttl)
        self.stats = Stats() if stats else None

    # ----- plumbing

    @property
    def s(self) -> requests.Session:
        if not hasattr(self._local, "s"):
            self._local.s = requests.Session()
        return self._local.s

    def _headers(self, key: Key) -> dict[str, str]:
        return {"Authorization": f"Bearer {key.value}", "Accept": "application/json"}

    def _key_order(self) -> list[Key]:
        with self._lock:
            live = [k for k in self.keys if not k.dead]
        if not live:
            raise RouterError(
                401, "All API keys were rejected (401/403). Check your keys."
            )
        with self._lock:
            start = self._rr % len(live)
        rotated = live[start:] + live[:start]
        now = time.time()
        return sorted(rotated, key=lambda k: not k.is_ready(now))

    def _rec(
        self, model: str, key: Key, outcome: str, latency: float | None = None
    ) -> None:
        if self.stats:
            self.stats.rec(model, key.label, outcome, latency)

    def _pair_fail(self, key: Key, model: str) -> None:
        with self._lock:
            p = self.pair.setdefault((key.value, model), [0.0, 0])
            p[1] += 1
            p[0] = time.time() + min(
                CFG.cooldown_err * 2 ** (p[1] - 1), PAIR_BACKOFF_CAP
            )

    def _pair_ok(self, key: Key, model: str) -> None:
        with self._lock:
            self.pair.pop((key.value, model), None)

    # ----- discovery / allowlist

    def available_ids(
        self, refresh: bool = False, ttl: int = MODEL_LIST_TTL
    ) -> list[str]:
        now = time.time()
        if refresh or self._available is None or now - self._available_at > ttl:
            last: Exception | None = None
            for key in self._key_order():
                try:
                    r = self.s.get(
                        f"{key.base_url}/models",
                        headers=self._headers(key),
                        timeout=30,
                    )
                except requests.RequestException as e:
                    last = e
                    continue
                if r.status_code in (401, 403):
                    key.mark_dead()
                    continue
                if r.status_code == 429:
                    key.bench(CFG.cooldown_429)
                    continue
                r.raise_for_status()
                self._available = [m["id"] for m in r.json().get("data", [])]
                self._available_at = time.time()
                return self._available
            raise RouterError(502, f"Could not list models with any key ({last})")
        return self._available or []

    def allowed(self, patterns: list[str], deny: bool = True) -> list[str]:
        """Resolve exact model IDs or explicit glob patterns against live availability."""
        out: list[str] = []
        available = self.available_ids()
        for pattern in patterns:
            for model_id in available:
                if (
                    fnmatch.fnmatchcase(model_id.casefold(), pattern.casefold())
                    and not (
                        deny
                        and any(
                            item.casefold() in model_id.casefold() for item in CFG.deny
                        )
                    )
                    and model_id not in out
                ):
                    out.append(model_id)
        return out

    def all_allowed(self) -> list[str]:
        pats = list(dict.fromkeys(p for v in CFG.routes.values() for p in v))
        return self.allowed(pats)

    def plan(
        self, body: dict[str, Any], route: str | None = None, model: str | None = None
    ) -> tuple[list[str], str]:
        """-> (candidate model ids, label)"""
        model = model or body.get("model")
        msgs = body.get("messages", [])
        name = (str(model or "auto")).lower()
        if route is None:
            if name in ("auto", "router", "free-auto", ""):
                route = classify(msgs)
            elif name.startswith("route:"):
                route = name[6:]
            elif name.startswith("free-") and name[5:] in CFG.routes:
                route = name[5:]
            elif name in CFG.routes:
                route = name
        if route:
            if route not in CFG.routes:
                raise RouterError(
                    400, f"unknown route '{route}', choose from {list(CFG.routes)}"
                )
            cands = self.allowed(CFG.routes[route])
            label = f"route:{route}"

        else:
            union = list(dict.fromkeys(p for v in CFG.routes.values() for p in v))
            cands = [m for m in self.allowed(union) if m.casefold() == name.casefold()]
            label = name
        if not cands:
            raise RouterError(
                404,
                f"no allowlisted model available for '{label}'. Run `list`, edit routes.",
            )
        return cands, label

    # ----- core dispatch

    def _try(
        self,
        endpoint: str,
        cands: list[str],
        body: dict[str, Any],
        stream: bool,
        errors: list[str],
    ) -> tuple[requests.Response, str, Key, float] | None:
        for m in cands:
            for key in self._key_order():
                now = time.time()
                pair = self.pair.get((key.value, m))
                if pair and pair[0] > now:
                    continue
                if not key.is_ready(now):
                    continue
                t0 = time.time()
                try:
                    key.limiter.wait()
                    resp = self.s.post(
                        f"{key.base_url}/{endpoint}",
                        headers=self._headers(key),
                        json={**body, "model": m},
                        timeout=CFG.timeout,
                        stream=stream,
                    )
                except requests.RequestException as e:
                    self._pair_fail(key, m)
                    self._rec(m, key, "fail")
                    errors.append(f"{m} [{key.label}]: {type(e).__name__}")
                    continue
                sc = resp.status_code
                if sc == 200:
                    self._pair_ok(key, m)
                    key.record_ok()
                    with self._lock:
                        self._rr += 1
                    return resp, m, key, t0
                text = resp.text[:160].replace("\n", " ")
                resp.close()
                if sc == 429:
                    try:
                        ra = max(
                            1.0,
                            min(
                                float(
                                    resp.headers.get("Retry-After", CFG.cooldown_429)
                                ),
                                RETRY_AFTER_CAP,
                            ),
                        )
                    except (ValueError, TypeError):
                        ra = float(CFG.cooldown_429)
                    key.record_429()
                    key.bench(ra)
                    self._rec(m, key, "429")
                    errors.append(f"{m} [{key.label}]: 429 -> next key")
                    log.info("429 on %s [%s], benched %.0fs", m, key.label, ra)
                    continue
                if sc in (401, 403):
                    key.mark_dead()
                    key.record_fail()
                    self._rec(m, key, "fail")
                    errors.append(f"{m} [{key.label}]: HTTP {sc} key disabled")
                    continue
                self._rec(m, key, "fail")
                errors.append(f"{m} [{key.label}]: HTTP {sc} {text}")
                if sc >= 500:
                    self._pair_fail(key, m)
                    continue
                break  # 4xx: this model rejects the request -> next model, not next key
        return None

    def _open(
        self,
        endpoint: str,
        cands: list[str],
        body: dict[str, Any],
        stream: bool = False,
    ) -> tuple[requests.Response, str, Key, float]:
        errors: list[str] = []
        for attempt in (1, 2):
            got = self._try(endpoint, cands, body, stream, errors)
            if got:
                return got
            live = [k for k in self.keys if not k.dead]
            if not live:
                raise RouterError(
                    401, "All API keys rejected (401/403):\n  " + "\n  ".join(errors)
                )
            soonest = min(k.benched_until for k in live) - time.time()
            if attempt == 1 and 0 < soonest <= CFG.max_wait:
                log.warning("all keys rate-limited, waiting %.0fs", soonest)
                time.sleep(soonest + 0.5)
                continue
            break
        status = 429 if any("429" in e for e in errors) else 502
        raise RouterError(
            status, "All routed models/keys failed:\n  " + "\n  ".join(errors)
        )

    # ----- public API

    def _body(
        self, messages: list[dict[str, Any]], kw: dict[str, Any]
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "messages": messages,
            "max_tokens": kw.pop("max_tokens", 1024),
        }
        body.update(kw)
        return body

    def chat_json(
        self,
        body: dict[str, Any],
        route: str | None = None,
        model: str | None = None,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        """OpenAI-style request body in, dict out: {json, model, key, cached}."""
        body = dict(body)
        body.pop("stream", None)
        cands, label = self.plan(body, route, model)
        ck: str | None = None
        if use_cache and body.get("temperature") == 0 and not body.get("tools"):
            ck = hashlib.sha256(
                json.dumps(
                    [
                        label,
                        list(cands),
                        {k: v for k, v in body.items() if k != "model"},
                    ],
                    sort_keys=True,
                ).encode()
            ).hexdigest()
            hit = self.cache.get(ck)
            if hit:
                return {**hit, "cached": True}
        resp, m, key, t0 = self._open("chat/completions", cands, body)
        lat = time.time() - t0
        data = resp.json()
        self._rec(m, key, "ok", lat)
        out: dict[str, Any] = {
            "json": data,
            "model": m,
            "key": key.label,
            "cached": False,
        }
        if ck:
            self.cache.put(ck, {k: out[k] for k in ("json", "model", "key")})
        return out

    def chat(
        self,
        messages: list[dict[str, Any]],
        route: str | None = None,
        model: str | None = None,
        **kw: Any,
    ) -> dict[str, Any]:
        out = self.chat_json(self._body(messages, kw), route=route, model=model)
        choices = out["json"].get("choices") or []
        msg = choices[0].get("message", {}) if choices else {}
        return {
            "model": out["model"],
            "key": out["key"],
            "text": msg.get("content") or "",
            "message": msg,
            "raw": out["json"],
            "cached": out["cached"],
        }

    def open_chat_stream(
        self, body: dict[str, Any], route: str | None = None, model: str | None = None
    ) -> tuple[requests.Response, str, Key]:
        """-> (upstream streaming response, model id, key). Fails over before the first byte."""
        body = dict(body)
        body["stream"] = True
        cands, _ = self.plan(body, route, model)
        resp, m, key, t0 = self._open("chat/completions", cands, body, stream=True)
        self._rec(m, key, "ok", time.time() - t0)
        return resp, m, key

    def chat_stream(
        self,
        messages: list[dict[str, Any]],
        route: str | None = None,
        model: str | None = None,
        **kw: Any,
    ) -> Iterator[str]:
        """Generator of text deltas. Always closes the upstream response on exit."""
        resp, _, _ = self.open_chat_stream(
            self._body(messages, kw), route=route, model=model
        )
        try:
            for line in resp.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    ch = json.loads(payload)["choices"]
                except (ValueError, KeyError):
                    continue
                if ch and (d := ch[0].get("delta", {}).get("content")):
                    yield d
        finally:
            resp.close()

    def embeddings(self, body: dict[str, Any]) -> dict[str, Any]:
        cands = self.allowed(CFG.embed_allow, deny=False)
        if not cands:
            raise RouterError(
                404, "no allowlisted embedding model available (config: embed_allow)"
            )
        resp, m, key, t0 = self._open("embeddings", cands, dict(body))
        self._rec(m, key, "ok", time.time() - t0)
        return resp.json()

    # ----- diagnostics

    def probe(self) -> dict[str, tuple[Any, float]]:
        res: dict[str, tuple[Any, float]] = {}
        for m in self.all_allowed():
            t0 = time.time()
            key = next(
                (k for k in self._key_order() if k.is_ready()), self._key_order()[0]
            )
            try:
                key.limiter.wait()
                r = self.s.post(
                    f"{key.base_url}/chat/completions",
                    headers=self._headers(key),
                    timeout=60,
                    json={
                        "model": m,
                        "max_tokens": 8,
                        "messages": [{"role": "user", "content": "Reply with: ok"}],
                    },
                )
                if r.status_code == 429:
                    key.bench(CFG.cooldown_429)
                elif r.status_code in (401, 403):
                    key.mark_dead()
                res[m] = (r.status_code, round(time.time() - t0, 2))
            except requests.RequestException as e:
                res[m] = (type(e).__name__, round(time.time() - t0, 2))
        return res

    def key_status(self) -> list[tuple[str, str, str, int, int]]:
        now, rows = time.time(), []
        for k in self.keys:
            st = (
                "DEAD (401/403)"
                if k.dead
                else "ready"
                if k.is_ready(now)
                else f"limited {k.benched_until - now:.0f}s"
            )
            rows.append((k.label, k.provider, st, k.ok, k.hits_429))
        return rows


# --------------------------------------------------------------------------- proxy server


# --------------------------------------------------------------------------- HTTP adapter

from zrouter_contracts import MAX_REQUEST_BYTES, RouterError
from zrouter_http import (
    _LOOPBACK_HOSTS,
    _read_body,
    _require_token_for_public_bind,
    make_handler as _make_http_handler,
    serve as _serve_http,
)


def make_handler(router: FreeRouter, token: str | None):
    """Compatibility wrapper for the public HTTP handler factory."""
    return _make_http_handler(router, token, CFG.routes)


def serve(router: FreeRouter, host: str, port: int, token: str | None) -> None:
    """Compatibility wrapper for the public proxy server entry point."""
    return _serve_http(router, host, port, token, CFG.routes)


# --------------------------------------------------------------------------- CLI

HELP_TOPICS: dict[str, str] = {
    "quickstart": """\
QUICKSTART
  1. Get free key(s) at https://build.nvidia.com  (keys start with nvapi-)
  2. export NVIDIA_API_KEYS="nvapi-aaa,nvapi-bbb"
  3. python zrouter.py list              # which allowlisted models exist
  4. python zrouter.py chat "hello"      # auto-routed chat
  5. python zrouter.py serve             # OpenAI-compatible proxy on :8000
""",
    "keys": """\
API KEYS
  Sources (merged, de-duplicated):
    NVIDIA_API_KEY      one key
    NVIDIA_API_KEYS     comma / space / newline separated
    --keys-file FILE    one key per line, '#' comments allowed
  On HTTP 429 the key is benched (Retry-After honoured) and the SAME model is
  retried on the next key. 401/403 marks a key dead. Keys are always masked in
  output. Use only keys that belong to you or your team.
  Check state with:  python zrouter.py keys
""",
    "routes": """\
ROUTES  (free-only allowlist; exact IDs or explicit glob patterns, first available match wins)
  auto       classify the prompt automatically (default for `chat` and the proxy)
  general    everyday questions
  code       code / debugging / regex / SQL / git
  reasoning  maths, logic, step-by-step analysis, very long prompts
  fast       short prompts, smallest models
  vision     messages containing images
  Model names accepted by `chat --model` and the proxy:
    auto | free-<route> | route:<route> | exact allowlisted model ID (e.g. glm-4.7)
    Config route patterns may use explicit glob syntax such as "nvidia/*-vision"
  Anything not on the allowlist is refused (HTTP 404), so paid models are never called.
  Edit routes with a config file (see: help config). See what resolves: `list`.
""",
    "serve": """\
PROXY SERVER
  python zrouter.py serve [--host 127.0.0.1] [--port 8000] [--token SECRET]
  Endpoints:
    POST /v1/chat/completions   (stream and non-stream, tools, images)
    POST /v1/embeddings
    GET  /v1/models   GET /health   GET /stats
  Client example:
    from openai import OpenAI
    c = OpenAI(base_url="http://127.0.0.1:8000/v1", api_key="SECRET")
    c.chat.completions.create(model="auto", messages=[{"role": "user", "content": "hi"}])
  Response headers: X-Router-Model, X-Router-Key (masked), X-Router-Cache.
  Binds to localhost by default. If you use --host 0.0.0.0, ALWAYS set --token / ROUTER_TOKEN.
""",
    "config": """\
CONFIG FILE  (--config router.json  or  NVIDIA_ROUTER_CONFIG=router.json)
  {
    "routes": {"code": ["glm-4.7", "deepseek-v3.2"]},   // replaces only the routes you list
    "deny": ["embed", "guard", "safety"],                // never route chat to ids containing these
    "embed_allow": ["nv-embed"],
    "rpm": 30,            // per-key requests/minute (free tier is about 40)
    "max_wait": 30,       // seconds to wait if every key is rate limited
    "cache_ttl": 600,     // seconds; 0 disables (cache only applies when temperature == 0)
    "timeout": 90,
    "base_url": "https://integrate.api.nvidia.com/v1"
  }
  (Remove the // comments in the real file; JSON does not allow them.)
""",
    "env": """\
ENVIRONMENT VARIABLES
  NVIDIA_API_KEY / NVIDIA_API_KEYS   API key(s)
  NVIDIA_BASE_URL                    default https://integrate.api.nvidia.com/v1
  NVIDIA_RPM                         per-key requests per minute (default 35)
  NVIDIA_MAX_WAIT                    max seconds to wait when all keys are limited (default 60)
  NVIDIA_CACHE_TTL                   cache seconds (default 3600, 0 = off)
  NVIDIA_ROUTER_CONFIG               path to router.json
  NVIDIA_ROUTER_HOME                 stats dir (default ~/.nvidia_free_router)
  ROUTER_TOKEN                       bearer token required by the proxy
""",
    "troubleshooting": """\
TROUBLESHOOTING
  "No API key"                      set NVIDIA_API_KEY(S) or --keys-file
  "no allowlisted model available"  run `list`; edit routes so the substrings match real ids
  429 / "all keys rate-limited"     add more keys, lower NVIDIA_RPM, or raise NVIDIA_MAX_WAIT
  401/403                           key invalid/expired; check `keys` (shows DEAD)
  404 on a model                    it is not on the allowlist (by design: free-only)
  Unsure what is happening          add -v for logs, or run `probe` to test each model
""",
}

MAIN_EPILOG = """\
examples:
  %(prog)s chat "write a regex for emails"        auto-routed
  %(prog)s chat "hi" --route fast --stream        pick a route, stream output
  %(prog)s serve --port 8000 --token secret       OpenAI-compatible proxy
  %(prog)s keys | list | probe | stats            diagnostics

more help:  %(prog)s help [quickstart|keys|routes|serve|config|env|troubleshooting]
"""


def print_help_topic(parser: argparse.ArgumentParser, topic: str | None) -> None:
    if topic in (None, "all"):
        parser.print_help()
        print()
        for t in HELP_TOPICS.values():
            print(t)
    elif topic in HELP_TOPICS:
        print(HELP_TOPICS[topic])
    else:
        sys.exit(
            f"unknown help topic '{topic}'. Topics: all, " + ", ".join(HELP_TOPICS)
        )


def build_parser() -> argparse.ArgumentParser:
    fmt = argparse.RawDescriptionHelpFormatter
    ap = argparse.ArgumentParser(
        prog="zrouter.py",
        formatter_class=fmt,
        epilog=MAIN_EPILOG,
        description="Free-only router for NVIDIA hosted NIM endpoints: model fallback, multi-key "
        "rotation on 429, auto routing, streaming, cache, stats and an OpenAI-compatible proxy.",
    )
    ap.add_argument(
        "--keys-file", metavar="FILE", help="file with one API key per line"
    )
    ap.add_argument(
        "--providers-file",
        metavar="FILE",
        default=os.environ.get("NVIDIA_PROVIDERS_FILE"),
        help="provider.json with per-provider API keys and base URLs (or NVIDIA_PROVIDERS_FILE)",
    )
    ap.add_argument(
        "--config",
        metavar="FILE",
        default=os.environ.get("NVIDIA_ROUTER_CONFIG"),
        help="JSON config overriding routes/limits (or NVIDIA_ROUTER_CONFIG)",
    )
    ap.add_argument(
        "-v", "--verbose", action="store_true", help="show routing/rate-limit logs"
    )
    sub = ap.add_subparsers(dest="cmd", metavar="COMMAND")

    def add(name: str, help_: str, **kw: Any) -> argparse.ArgumentParser:
        return sub.add_parser(
            name, help=help_, description=help_, formatter_class=fmt, **kw
        )

    add(
        "keys",
        "show each API key (masked): ready / limited / dead, success and 429 counts",
    )
    add("list", "list allowlisted models that currently exist, grouped by route")
    m = add(
        "models",
        "list catalog models with free/paid/provider metadata (no API key needed)",
    )
    m.add_argument(
        "--provider",
        metavar="PROVIDER",
        help="filter by provider (e.g. NVIDIA, Google)",
    )
    m.add_argument("--free", action="store_true", help="show only free models")
    m.add_argument("--paid", action="store_true", help="show only paid models")
    d = add(
        "discover",
        "auto-discover models from the NVIDIA API and update models.json",
    )
    d.add_argument("--keys-file", metavar="FILE", help="file with one API key per line")
    d.add_argument(
        "--output",
        metavar="FILE",
        default="models.json",
        help="output catalog path (default: models.json)",
    )
    p = add(
        "providers",
        "list configured providers with API key counts and base URLs (no API key needed)",
    )
    p.add_argument(
        "--file",
        metavar="FILE",
        default=None,
        help="provider.json path (default: provider.json or NVIDIA_PROVIDERS_FILE)",
    )
    add(
        "probe",
        "send a tiny request to every allowlisted model and report status + latency",
    )
    add("stats", "show saved per-model and per-key statistics (no API key needed)")
    c = add(
        "chat",
        "send one prompt through the router",
        epilog='example:  %(prog)s "explain TCP slow start" --route reasoning --stream',
    )
    c.add_argument("prompt", help="the user message")
    c.add_argument(
        "--route",
        help="force a route (default: auto-classify). Any route name defined in "
        "routes (default or config); validated at request time.",
    )
    c.add_argument(
        "--model",
        help="specific allowlisted model, any substring of its id (e.g. glm-4.7)",
    )
    c.add_argument("--system", help="optional system prompt")
    c.add_argument(
        "--max-tokens", type=int, default=1024, metavar="N", help="default 1024"
    )
    c.add_argument("--stream", action="store_true", help="print tokens as they arrive")
    s = add(
        "serve",
        "run a local OpenAI-compatible proxy (chat, embeddings, models, health, stats)",
        epilog="client base_url: http://HOST:PORT/v1   model: auto | free-code | glm-4.7 ...",
    )
    s.add_argument(
        "--host", default="127.0.0.1", help="default 127.0.0.1 (localhost only)"
    )
    s.add_argument("--port", type=int, default=8000, help="default 8000")
    s.add_argument(
        "--token",
        default=os.environ.get("ROUTER_TOKEN"),
        help="require 'Authorization: Bearer TOKEN' (or ROUTER_TOKEN); "
        "strongly advised if host is not 127.0.0.1",
    )
    b = add(
        "bot",
        "bot framework: status, vault, memory, approvals, routines, skills, files, meetings",
    )
    b.add_argument(
        "subcmd",
        help="subcommand: status, vault, memory, approval, approve, deny, routine, skill, file, meeting, page, agent, email, calendar, media, cart, network, health",
    )
    b.add_argument(
        "arg",
        nargs="?",
        help="subcommand argument (e.g. card id, skill id, file name, memory key)",
    )
    b.add_argument(
        "arg2",
        nargs="?",
        help="second subcommand argument (e.g. vault id, memory key, value)",
    )
    b.add_argument(
        "arg3",
        nargs="?",
        help="third subcommand argument",
    )
    b.add_argument(
        "arg4",
        nargs="?",
        help="fourth subcommand argument",
    )
    b.add_argument("--value", help="value for memory set or vault update")
    b.add_argument("--value2", help="second value for cart items (quantity)")
    b.add_argument("--details", help="details for approval card creation")
    b.add_argument(
        "--schedule", help="schedule for routine (e.g. daily 09:00, every 1 hour)"
    )
    b.add_argument("--title", help="meeting/page title")
    b.add_argument(
        "--platform", help="meeting platform (zoom, google_meet, microsoft_teams)"
    )
    b.add_argument("--link", help="meeting link URL")
    b.add_argument("--at", type=float, help="meeting scheduled time (unix timestamp)")
    b.add_argument("--mode", help="agent mode (code, research, analysis, writing)")
    b.add_argument("--task", help="cloud agent task description")
    b.add_argument("--from", dest="from_addr", help="email from address")
    b.add_argument("--to", dest="to_addr", help="email to address")
    b.add_argument("--subject", help="email subject")
    b.add_argument("--body", help="email/message body")
    h = add(
        "help",
        "detailed help: quickstart, keys, routes, serve, config, env, troubleshooting",
    )
    h.add_argument(
        "topic", nargs="?", default="all", help="all (default) or one topic name"
    )
    return ap


def main() -> None:
    ap = build_parser()
    a = ap.parse_args()
    if a.cmd is None:
        ap.print_help()
        print("\nNew here? run:  python zrouter.py help quickstart")
        return
    if a.cmd == "help":
        return print_help_topic(ap, a.topic)

    if a.cmd == "bot":
        _bot_cmd(a)
        return

    logging.basicConfig(
        level=logging.INFO if a.verbose or a.cmd == "serve" else logging.WARNING,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    if a.config:
        CFG.load(a.config)

    if a.cmd == "stats":
        data = Stats().data
        print(f"{'model':<48}{'ok':>6}{'fail':>6}{'429':>6}{'avg s':>8}")
        for m, v in sorted(data["models"].items()):
            avg = v["lat_sum"] / v["ok"] if v["ok"] else 0
            print(f"{m:<48}{v['ok']:>6}{v['fail']:>6}{v['429']:>6}{avg:>8.2f}")
        print(f"\n{'key':<24}{'ok':>6}{'fail':>6}{'429':>6}")
        for k, v in data["keys"].items():
            print(f"{k:<24}{v['ok']:>6}{v['fail']:>6}{v['429']:>6}")
        return

    if a.cmd == "models":
        models = CATALOG.models
        if a.provider:
            models = CATALOG.by_provider(a.provider)
        if a.free:
            models = CATALOG.list_free()
        if a.paid:
            models = CATALOG.list_paid()
        if not models:
            print("No models match the given filters.")
            return
        print(f"{'model':<40}{'provider':<16}{'tier':<8}{'routes':<24}{'description'}")
        print("-" * 110)
        for m in sorted(models, key=lambda x: str(x.get("id", ""))):
            mid = str(m.get("id", ""))
            prov = str(m.get("provider", "unknown"))
            tier = "free" if m.get("free") else "paid"
            routes = ",".join(m.get("routes", []))
            desc = str(m.get("description", ""))
            print(f"{mid:<40}{prov:<16}{tier:<8}{routes:<24}{desc}")
        return

    if a.cmd == "providers":
        print(f"{'provider':<16}{'base_url':<45}{'keys':>6}{'env_var':<20}")
        print("-" * 90)
        for p in PROVIDERS.list_providers():
            name = str(p["name"])
            base = str(p["base_url"])
            nkeys = str(p["key_count"])
            env = str(p["env_var"])
            print(f"{name:<16}{base:<45}{nkeys:>6}{env:<20}")
        return

    try:
        r = FreeRouter(keys_file=a.keys_file, providers_file=a.providers_file)
    except RouterError as e:
        sys.exit(f"error {e.status}: {e.message}")
    try:
        if a.cmd == "keys":
            for label, prov, st, ok, n429 in r.key_status():
                print(f"{label:<22} {prov:<16} {st:<16} ok={ok} 429s={n429}")
        elif a.cmd == "list":
            for route, pats in CFG.routes.items():
                print(f"[{route}]")
                for m in r.allowed(pats):
                    print("  ", m)
        elif a.cmd == "probe":
            for m, (status, secs) in r.probe().items():
                print(f"{status!s:>6}  {secs:>6}s  {m}")
        elif a.cmd == "chat":
            msgs = ([{"role": "system", "content": a.system}] if a.system else []) + [
                {"role": "user", "content": a.prompt}
            ]
            if a.stream:
                for d in r.chat_stream(
                    msgs, route=a.route, model=a.model, max_tokens=a.max_tokens
                ):
                    print(d, end="", flush=True)
                print()
            else:
                out = r.chat(
                    msgs, route=a.route, model=a.model, max_tokens=a.max_tokens
                )
                print(f"# model: {out['model']}  key: {out['key']}\n{out['text']}")
        elif a.cmd == "serve":
            serve(r, a.host, a.port, a.token)
        elif a.cmd == "discover":
            count = CATALOG.update_from_router(r)
            CATALOG.save(a.output)
            free = len(CATALOG.list_free())
            paid = len(CATALOG.list_paid())
            print(f"Discovered {count} model(s) from NVIDIA API -> {a.output}")
            print(f"  free: {free}  paid: {paid}")
            providers = sorted({m.get("provider", "unknown") for m in CATALOG.models})
            print(f"  providers: {', '.join(providers)}")
    except RouterError as e:
        sys.exit(f"error {e.status}: {e.message}")
    finally:
        if r.stats:
            r.stats.flush()


def _bot_cmd(a: Any) -> None:
    """Handle bot subcommands."""
    bot = get_bot()

    if a.subcmd == "status":
        d = bot.to_dict()
        print(f"Bot: {d['name']} (id={d['id']})")
        print(f"  Status: {d['status_phrase']} ({d['status']})")
        print(f"  Vault entries: {d['vault_entries']}")
        print(f"  Memory keys: {d['memory_keys']}")
        print(f"  Pending approvals: {d['pending_approvals']}")

    elif a.subcmd == "health":
        report = BotHealth(bot).report()
        for k, v in report.items():
            print(f"  {k}: {v}")

    elif a.subcmd == "vault":
        if a.arg == "list":
            entries = bot.vault_list()
            if not entries:
                print("  No vault entries.")
            for e in entries:
                print(f"  {e.id[:8]}  {e.kind:<12} {e.name}")
        elif a.arg == "get" and a.arg2:
            e = bot.vault_get(a.arg2)
            if e:
                print(f"  {e.name} ({e.kind}): {e.value}")
            else:
                print(f"  Vault entry {a.arg2} not found.")
        elif a.arg == "add" and a.arg2 and a.value:
            import json as _json

            try:
                val = _json.loads(a.value)
            except (ValueError, TypeError):
                val = {"raw": a.value}
            e = VaultEntry(id=str(uuid.uuid4()), name=a.arg2, kind="secret", value=val)
            bot.vault_add(e)
            print(f"  Added vault entry {e.id[:8]}: {e.name}")
        elif a.arg == "delete" and a.arg2:
            ok = bot.vault_delete(a.arg2)
            print(f"  Deleted: {ok}")
        else:
            print(
                "  Usage: zrouter bot vault list | get <id> | add <name> <value> | delete <id>"
            )

    elif a.subcmd == "memory":
        if a.arg == "list":
            mem = bot.all_memory()
            if not mem:
                print("  No memory entries.")
            for k, v in mem.items():
                print(f"  {k}: {v}")
        elif a.arg == "get" and a.arg2:
            print(f"  {a.arg2}: {bot.recall(a.arg2)}")
        elif a.arg == "set" and a.arg2 and a.value:
            bot.remember(a.arg2, a.value)
            print(f"  Set {a.arg2} = {a.value}")
        elif a.arg == "delete" and a.arg2:
            ok = bot.forget(a.arg2)
            print(f"  Deleted: {ok}")
        else:
            print(
                "  Usage: zrouter bot memory list | get <key> | set <key> --value <value> | delete <key>"
            )

    elif a.subcmd == "approval":
        cards = bot.pending_approvals()
        if not cards:
            print("  No pending approvals.")
        for c in cards:
            print(f"  {c.id[:8]}  {c.action:<20} {c.status.value:<12} {c.details}")

    elif a.subcmd == "approve" and a.arg:
        card = bot.approve_card(a.arg, decided_by="cli")
        if card:
            print(f"  Approved: {card.action}")
        else:
            print(f"  Card {a.arg} not found or already decided.")

    elif a.subcmd == "deny" and a.arg:
        card = bot.deny_card(a.arg, decided_by="cli")
        if card:
            print(f"  Denied: {card.action}")
        else:
            print(f"  Card {a.arg} not found or already decided.")

    elif a.subcmd == "routine":
        scheduler = RoutineScheduler()
        if a.arg == "list":
            routines = scheduler.list()
            if not routines:
                print("  No routines.")
            for r in routines:
                print(f"  {r.id[:8]}  {r.name:<20} {r.status.value:<12} {r.schedule}")
        elif a.arg == "add" and a.arg2:
            routine = Routine(
                id=str(uuid.uuid4()),
                name=a.arg2,
                action="chat",
                params={"prompt": a.value or ""},
                schedule=a.schedule or "daily 09:00",
            )
            scheduler.add(routine)
            print(f"  Added routine {routine.id[:8]}: {routine.name}")
        else:
            print("  Usage: zrouter bot routine list | add <name> [schedule]")

    elif a.subcmd == "skill":
        library = SkillLibrary()
        if a.arg == "list":
            skills = library.list()
            if not skills:
                print("  No skills.")
            for s in skills:
                print(
                    f"  {s.id[:8]}  {s.name:<20} {s.category:<12} params={','.join(s.parameters)}"
                )
        elif a.arg == "use" and a.arg2 and a.value:
            import json as _json

            try:
                params = _json.loads(a.value)
            except (ValueError, TypeError):
                params = {"text": a.value}
            result = library.use(a.arg2, params)
            print(f"  {result}")
        else:
            print("  Usage: zrouter bot skill list | use <id> --value <json>")

    elif a.subcmd == "file":
        fh = FileHandler()
        if a.arg == "list":
            files = fh.list_files()
            if not files:
                print("  No files.")
            for f in files:
                print(f"  {f['name']:<40} {f['size']:>10} bytes  {f['extension']}")
        elif a.arg == "upload" and a.arg2:
            from pathlib import Path as _Path

            p = _Path(a.arg2)
            if p.exists():
                meta = fh.save_file(p.name, p.read_bytes())
                print(
                    f"  Uploaded: {meta['id'][:8]}  {meta['original_name']} ({meta['size']} bytes)"
                )
            else:
                print(f"  File not found: {a.arg2}")
        else:
            print("  Usage: zrouter bot file list | upload <path>")

    elif a.subcmd == "meeting":
        mm = MeetingManager()
        if a.arg == "list":
            meetings = mm.list()
            if not meetings:
                print("  No meetings.")
            for m in meetings:
                print(f"  {m.id[:8]}  {m.title:<25} {m.platform:<15} {m.status}")
        elif a.arg == "add" and a.title and a.platform and a.link and a.at is not None:
            m = mm.schedule(a.title, a.platform, a.link, a.at)
            print(f"  Scheduled: {m.title} ({m.platform}) id={m.id[:8]}")
        elif a.arg == "join" and a.arg2:
            m = mm.join(a.arg2)
            if m:
                print(f"  Joined: {m.title} ({m.platform})")
            else:
                print(f"  Meeting {a.arg2} not found.")
        else:
            print(
                "  Usage: zrouter bot meeting list | add --title <t> --platform <p> --link <url> --at <ts> | join <id>"
            )

    elif a.subcmd == "page":
        pm = PageManager()
        if a.arg == "list":
            pages = pm.list_for_bot(bot.id)
            if not pages:
                print("  No pages.")
            for p in pages:
                print(
                    f"  {p.id[:8]}  {p.title:<25} {'owner' if p.owner_bot_id == bot.id else 'shared'}"
                )
        elif a.arg == "create" and a.arg2 and a.value:
            page = pm.create(a.arg2, a.value, bot.id)
            print(f"  Created page: {page.title} id={page.id[:8]}")
        elif a.arg == "get" and a.arg2:
            p = pm.get(a.arg2)
            if p:
                print(f"  {p.title}: {p.content[:100]}...")
            else:
                print(f"  Page {a.arg2} not found.")
        elif a.arg == "update" and a.arg2 and a.value:
            p = pm.update(a.arg2, a.value)
            if p:
                print(f"  Updated page: {p.title}")
            else:
                print(f"  Page {a.arg2} not found.")
        elif a.arg == "share" and a.arg2:
            p = pm.share_with(a.arg2, bot.id)
            if p:
                print(f"  Shared page: {p.title}")
            else:
                print(f"  Page {a.arg2} not found.")
        elif a.arg == "delete" and a.arg2:
            ok = pm.delete(a.arg2)
            print(f"  Deleted: {ok}")
        else:
            print(
                "  Usage: zrouter bot page list | create <title> --value <content> | get <id> | update <id> --value <content> | share <id> | delete <id>"
            )

    elif a.subcmd == "agent":
        cam = CloudAgentManager()
        if a.arg2 == "list":
            agents = cam.list()
            if not agents:
                print("  No agents.")
            for ag in agents:
                print(f"  {ag.id[:8]}  {ag.name:<20} {ag.mode:<12} {ag.status}")
        elif a.arg == "create" and a.arg2 and a.mode and a.task:
            agent = cam.create(a.arg2, a.mode, a.task)
            print(f"  Created agent: {agent.name} ({agent.mode}) id={agent.id[:8]}")
        elif a.arg == "start" and a.arg2:
            agent = cam.start(a.arg3)
            if agent:
                print(f"  Started agent: {agent.name}")
            else:
                print(f"  Agent {a.arg3} not found.")
        elif a.arg == "complete" and a.arg2 and a.value:
            agent = cam.complete(a.arg2, a.value)
            if agent:
                print(f"  Completed agent: {agent.name}")
            else:
                print(f"  Agent {a.arg3} not found.")
        elif a.arg == "fail" and a.arg2 and a.value:
            agent = cam.fail(a.arg2, a.value)
            if agent:
                print(f"  Failed agent: {agent.name}")
            else:
                print(f"  Agent {a.arg3} not found.")
        elif a.arg == "delete" and a.arg2:
            ok = cam.delete(a.arg3)
            print(f"  Deleted: {ok}")
        else:
            print(
                "  Usage: zrouter bot agent list | create <name> --mode <m> --task <t> | start <id> | complete <id> --value <result> | fail <id> --value <error> | delete <id>"
            )

    elif a.subcmd == "email":
        em = EmailManager()
        if a.arg == "list":
            emails = em.list()
            if not emails:
                print("  No emails.")
            for e in emails:
                print(
                    f"  {e.id[:8]}  {e.subject:<30} {e.from_addr:<20} -> {e.to_addr:<20} {e.status}"
                )
        elif a.arg == "draft" and a.from_addr and a.to_addr and a.subject and a.body:
            email = em.draft(a.from_addr, a.to_addr, a.subject, a.body)
            print(f"  Drafted email: {email.subject} id={email.id[:8]}")
        elif a.arg == "send" and a.arg2:
            email = em.send(a.arg2)
            if email:
                print(f"  Sent email: {email.subject}")
            else:
                print(f"  Email {a.arg2} not found.")
        elif a.arg == "delete" and a.arg2:
            ok = em.delete(a.arg2)
            print(f"  Deleted: {ok}")
        else:
            print(
                "  Usage: zrouter bot email list | draft --from <f> --to <t> --subject <s> --body <b> | send <id> | delete <id>"
            )

    elif a.subcmd == "calendar":
        cal = CalendarManager()
        if a.arg == "list":
            events = cal.list()
            if not events:
                print("  No events.")
            for e in events:
                print(f"  {e.id[:8]}  {e.title:<25} {e.status}")
        elif a.arg == "create" and a.arg2 and a.at is not None and a.value:
            event = cal.create(a.title, a.at, a.at + 3600, a.value)
            print(f"  Created event: {event.title} id={event.id[:8]}")
        elif a.arg == "cancel" and a.arg2:
            event = cal.cancel(a.arg2)
            if event:
                print(f"  Cancelled event: {event.title}")
            else:
                print(f"  Event {a.arg2} not found.")
        else:
            print(
                "  Usage: zrouter bot calendar list | create <title> --at <ts> --value <desc> | cancel <id>"
            )

    elif a.subcmd == "media":
        mm = MediaManager()
        if a.arg == "list":
            assets = mm.list()
            if not assets:
                print("  No media assets.")
            for a_ in assets:
                print(
                    f"  {a_.id[:8]}  {a_.title:<25} {a_.media_type:<8} {a_.size_bytes} bytes"
                )
        elif a.arg == "create" and a.arg2 and a.mode and a.value:
            asset = mm.create(
                a.title, a.media_type, a.value, a.value, len(a.value.encode())
            )
            print(
                f"  Created media: {asset.title} ({asset.media_type}) id={asset.id[:8]}"
            )
        elif a.arg == "delete" and a.arg2:
            ok = mm.delete(a.arg2)
            print(f"  Deleted: {ok}")
        else:
            print(
                "  Usage: zrouter bot media list | create <title> --mode <image|video> --value <prompt|path> | delete <id>"
            )

    elif a.subcmd == "cart":
        cm = CartManager()
        if a.arg == "list":
            carts = cm.list_for_bot(bot.id)
            if not carts:
                print("  No carts.")
            for c in carts:
                print(
                    f"  {c.id[:8]}  {c.status:<12} total=${c.total():.2f} items={len(c.items)}"
                )
        elif a.arg == "add-item" and a.arg2 and a.value and a.value2:
            try:
                price = float(a.value)
                quantity = int(a.value2)
            except (ValueError, TypeError):
                print(
                    "  Error: price must be a number and quantity must be an integer."
                )
            else:
                carts = cm.list_for_bot(bot.id)
                if carts:
                    cart = carts[0]
                else:
                    cart = cm.create(bot.id)
                cart = cm.add_item(cart.id, a.arg2, price, quantity, a.arg3 or "")
                print(f"  Added item to cart: {a.arg2}")
        elif a.arg == "checkout" and a.arg2:
            cart = cm.checkout(a.arg2)
            if cart:
                print(f"  Checked out cart: total=${cart.total():.2f}")
            else:
                print(f"  Cart {a.arg2} not found.")
        else:
            print(
                "  Usage: zrouter bot cart list | add-item <name> --value <price> --value2 <qty> [url] | checkout <id>"
            )

    elif a.subcmd == "network":
        nm = NetworkManager()
        if a.arg == "list":
            peers = nm.list()
            if not peers:
                print("  No peers.")
            for p in peers:
                print(f"  {p.id[:8]}  {p.name:<20} {p.ip:<20} {p.status}")
        elif a.arg == "add" and a.arg2 and a.arg3:
            peer = nm.add_peer(a.arg2, a.arg3)
            print(f"  Added peer: {peer.name} ({peer.ip})")
        elif a.arg == "status" and a.arg2:
            peer = nm.update_status(a.arg2, a.arg3 or "online")
            if peer:
                print(f"  Peer status: {peer.status}")
            else:
                print(f"  Peer {a.arg2} not found.")
        elif a.arg == "delete" and a.arg2:
            ok = nm.delete(a.arg2)
            print(f"  Deleted: {ok}")
        else:
            print(
                "  Usage: zrouter bot network list | add <name> <ip> | status <id> <online|offline> | delete <id>"
            )

    else:
        print(
            "  Unknown bot subcommand. Use: status, health, vault, memory, approval, approve, deny, routine, skill, file, meeting, page, agent, email, calendar, media, cart, network"
        )


if __name__ == "__main__":
    main()
