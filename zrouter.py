#!/usr/bin/env python3
"""
zrouter.py — backward-compatible public facade for the NVIDIA NIM router.

The implementation is split into configuration, catalog, application, HTTP,
runtime, bot, and CLI modules. Existing public imports and the executable
entry point remain available from this module.
"""

from __future__ import annotations

import logging

from zrouter_application import (
    CODE_RE,
    REASON_RE,
    FreeRouter,
    _text_of,
    classify,
    has_image,
)
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
from zrouter_catalog import CATALOG, MODELS_PATH, ModelsCatalog
from zrouter_cli import (
    HELP_TOPICS,
    MAIN_EPILOG,
    _bot_cmd,
    build_parser,
    main,
    print_help_topic,
)
from zrouter_config import (
    CFG,
    DEFAULT_CACHE_SIZE,
    DEFAULT_CACHE_TTL,
    DEFAULT_COOLDOWN_429,
    DEFAULT_COOLDOWN_ERR,
    DEFAULT_DENY,
    DEFAULT_EMBED_ALLOW,
    DEFAULT_MAX_WAIT,
    DEFAULT_ROUTES,
    DEFAULT_RPM,
    DEFAULT_TIMEOUT,
    MODEL_LIST_TTL,
    PAIR_BACKOFF_CAP,
    PROVIDERS,
    PROVIDERS_PATH,
    RETRY_AFTER_CAP,
    Key,
    ProviderConfig,
    Settings,
    _resource_path,
    load_keys,
    read_secret_file,
)
from zrouter_contracts import MAX_REQUEST_BYTES, RouterError
from zrouter_core import ProviderRegistry, validate_base_url
import zrouter_http as _zrouter_http
from zrouter_runtime import RateLimiter, Stats, TTLCache, mask

__all__ = [
    "CATALOG",
    "CFG",
    "CODE_RE",
    "DEFAULT_CACHE_SIZE",
    "DEFAULT_CACHE_TTL",
    "DEFAULT_COOLDOWN_429",
    "DEFAULT_COOLDOWN_ERR",
    "DEFAULT_DENY",
    "DEFAULT_EMBED_ALLOW",
    "DEFAULT_MAX_WAIT",
    "DEFAULT_ROUTES",
    "DEFAULT_RPM",
    "DEFAULT_TIMEOUT",
    "HELP_TOPICS",
    "MAIN_EPILOG",
    "MAX_REQUEST_BYTES",
    "MODELS_PATH",
    "MODEL_LIST_TTL",
    "PAIR_BACKOFF_CAP",
    "PROVIDERS",
    "PROVIDERS_PATH",
    "REASON_RE",
    "RETRY_AFTER_CAP",
    "BotHealth",
    "CalendarManager",
    "CartManager",
    "CloudAgentManager",
    "EmailManager",
    "FileHandler",
    "FreeRouter",
    "Key",
    "MediaManager",
    "MeetingManager",
    "ModelsCatalog",
    "NetworkManager",
    "PageManager",
    "ProviderConfig",
    "ProviderRegistry",
    "RateLimiter",
    "RouterError",
    "Routine",
    "RoutineScheduler",
    "Settings",
    "SkillLibrary",
    "Stats",
    "TTLCache",
    "VaultEntry",
    "_bot_cmd",
    "_read_body",
    "_resource_path",
    "_text_of",
    "build_parser",
    "classify",
    "get_bot",
    "has_image",
    "load_keys",
    "main",
    "make_handler",
    "mask",
    "print_help_topic",
    "read_secret_file",
    "serve",
    "validate_base_url",
]

log = logging.getLogger("nvrouter")
_read_body = _zrouter_http._read_body
_make_http_handler = _zrouter_http.make_handler
_serve_http = _zrouter_http.serve


def make_handler(router: FreeRouter, token: str | None):
    """Compatibility wrapper for the public HTTP handler factory."""
    return _make_http_handler(router, token, CFG.routes)


def serve(router: FreeRouter, host: str, port: int, token: str | None) -> None:
    """Compatibility wrapper for the public proxy server entry point."""
    _serve_http(router, host, port, token, CFG.routes)


if __name__ == "__main__":
    main()
