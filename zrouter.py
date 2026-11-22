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
    FreeRouter as FreeRouter,
    _text_of as _text_of,
    classify as classify,
    has_image as has_image,
)
from zrouter_bot import (
    BotHealth as BotHealth,
    CalendarManager as CalendarManager,
    CartManager as CartManager,
    CloudAgentManager as CloudAgentManager,
    EmailManager as EmailManager,
    FileHandler as FileHandler,
    MediaManager as MediaManager,
    MeetingManager as MeetingManager,
    NetworkManager as NetworkManager,
    PageManager as PageManager,
    Routine as Routine,
    RoutineScheduler as RoutineScheduler,
    SkillLibrary as SkillLibrary,
    VaultEntry as VaultEntry,
    get_bot as get_bot,
)
from zrouter_catalog import (
    CATALOG as CATALOG,
    MODELS_PATH as MODELS_PATH,
    ModelsCatalog as ModelsCatalog,
)
from zrouter_cli import (
    HELP_TOPICS as HELP_TOPICS,
    MAIN_EPILOG as MAIN_EPILOG,
    _bot_cmd as _bot_cmd,
    build_parser as build_parser,
    main as main,
    print_help_topic as print_help_topic,
)
from zrouter_config import (
    CFG as CFG,
    DEFAULT_CACHE_SIZE as DEFAULT_CACHE_SIZE,
    DEFAULT_CACHE_TTL as DEFAULT_CACHE_TTL,
    DEFAULT_COOLDOWN_429 as DEFAULT_COOLDOWN_429,
    DEFAULT_COOLDOWN_ERR as DEFAULT_COOLDOWN_ERR,
    DEFAULT_DENY as DEFAULT_DENY,
    DEFAULT_EMBED_ALLOW as DEFAULT_EMBED_ALLOW,
    DEFAULT_MAX_WAIT as DEFAULT_MAX_WAIT,
    DEFAULT_ROUTES as DEFAULT_ROUTES,
    DEFAULT_RPM as DEFAULT_RPM,
    DEFAULT_TIMEOUT as DEFAULT_TIMEOUT,
    MODEL_LIST_TTL as MODEL_LIST_TTL,
    PAIR_BACKOFF_CAP as PAIR_BACKOFF_CAP,
    PROVIDERS as PROVIDERS,
    PROVIDERS_PATH as PROVIDERS_PATH,
    RETRY_AFTER_CAP as RETRY_AFTER_CAP,
    Key as Key,
    ProviderConfig as ProviderConfig,
    Settings as Settings,
    _resource_path as _resource_path,
    load_keys as load_keys,
)
from zrouter_contracts import (
    MAX_REQUEST_BYTES as MAX_REQUEST_BYTES,
    RouterError as RouterError,
)
from zrouter_http import (
    _read_body as _http_read_body,
    make_handler as _make_http_handler,
    serve as _serve_http,
)
from zrouter_runtime import (
    RateLimiter as RateLimiter,
    Stats as Stats,
    TTLCache as TTLCache,
    mask as mask,
)

log = logging.getLogger("nvrouter")

_read_body = _http_read_body


def make_handler(router: FreeRouter, token: str | None):
    """Compatibility wrapper for the public HTTP handler factory."""
    return _make_http_handler(router, token, CFG.routes)


def serve(router: FreeRouter, host: str, port: int, token: str | None) -> None:
    """Compatibility wrapper for the public proxy server entry point."""
    _serve_http(router, host, port, token, CFG.routes)


if __name__ == "__main__":
    main()
