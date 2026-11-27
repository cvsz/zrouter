# Changelog

All notable changes to zrouter will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-11-15

### Added

- **Core Router**: Full-featured OpenAI-compatible proxy/router for NVIDIA NIM endpoints
- **Model Allowlisting**: Free-only model filtering to prevent accidental paid model calls
- **Multi-Key Rotation**: Automatic key rotation on HTTP 429 with Retry-After honoring
- **Per-Key Rate Limiting**: Token-bucket style rate limiter per API key
- **Exponential Backoff**: Per (key, model) pair backoff on failures
- **Streaming Support**: SSE streaming with failover before the first byte
- **Response Caching**: Cache for temperature == 0, no tools, non-stream requests
- **Persistent Stats**: Per model / per key counters (ok, fail, 429, latency)
- **OpenAI-Compatible Proxy**: Full /v1/chat/completions, /v1/embeddings endpoints
- **CLI**: `chat`, `list`, `probe`, `stats`, `keys`, `serve`, `models`, `discover`, `providers`
- **GUI**: Tkinter-based desktop GUI (`zrouter-gui.py`)
- **TUI**: Textual-based terminal UI (`zrouter-tui.py`)
- **Models Catalog**: 40 models across 14 providers with free/paid metadata
- **Provider Configuration**: provider.json for multi-provider API key management
- **CLI Executable**: `zrouter` shell script entry point

### Features Implemented

- Model discovery from NVIDIA API
- Per-key rate limiting with token bucket
- Key rotation on HTTP 429 with bench/cooldown
- Per-key rate limiting and exponential backoff
- Stream failover before first byte
- Response caching for temperature == 0
- Persistent stats (per model / per key)
- Local OpenAI-compatible proxy server
- JSON config file for routes / limits
- Thread-safe, type-annotated, input-validated

### Bug Fixes

- Fixed TUI Static.expand crash
- Fixed plan() route fallback for live-discovered models
- Key rotation status view
- Cache only when temperature == 0
- Streaming failover before first byte

### Bugs Fixed

- `key.dead`, `key.benched_until`, `hits_429`, `ok` accessed without lock in multi-threaded environments
- `chat()` crash with `IndexError` when NVIDIA sends empty `choices`
- `available_ids()` cached model list permanently without expiration
- `--route` CLI received only route in `DEFAULT_ROUTES`, rejected route added via config
- `chat_stream()` may close upstream response if client cancels mid-stream
- `Settings.load()` used `setattr` without validation

### Architecture Upgrades

- Separated configuration layer (`Settings`) from router (`FreeRouter`) clearly
- `Settings.load()` validates type of each key
- `Stats` uses atomic file writing (`tmp + os.replace`)
- `TTLCache` supports TTL and LRU eviction with lock
- `RouterError` attaches HTTP status code every time
- `_read_body()` combines reading and converting request body with size limit

### Security

- API key masking in logs and display
- Request body size limit (16 MiB hard cap)
- Request body must be JSON object
- Paid model rejection (allowlist enforcement)
- Thread-safe counters and state management

## [0.1.0] - 2026-11-01

### Added

- Initial release of NVIDIA Free-Model Router
- Basic chat functionality
- Model allowlisting
- Key rotation on 429
- Basic CLI
