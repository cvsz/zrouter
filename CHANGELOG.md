# Changelog

All notable changes to zrouter will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security
- Replace plaintext bot-vault persistence with native OS credential-store integration; reject unsupported/insecure backends and disable plaintext fallback.
- Detect legacy plaintext vault files and require explicit migration; keep credential values out of the on-disk JSON index.
- Add an HTTP adapter module and shared router error/request-size contracts while retaining the existing zrouter.py compatibility surface.


- Fail closed when live model discovery cannot match an explicitly configured route allowlist; no fallback to arbitrary live models.
- Do not infer a model's free/paid status from its name or route classification.
- Require exact model IDs or explicit glob patterns for route matching.
- Validate provider base URLs and reject non-loopback plaintext HTTP, embedded credentials, query strings, and fragments.

### Changed
- Extract 3 bot enums and 17 serializable domain models into `zrouter_bot_models.py`; keep their original `zrouter_bot` import paths as compatibility re-exports.
- Extract `Vault`, `Memory`, and bot-home storage paths into `zrouter_bot_storage.py`; preserve the original `zrouter_bot` import surface.
- Extract `RateLimiter`, `Stats`, `TTLCache`, and `mask` into `zrouter_runtime.py`; preserve their original `zrouter` import paths.
- Include the extracted module in Python packaging, Docker images, Makefile source bundles, lint, and regression tests.
- Introduce a dedicated provider registry module while preserving the existing ProviderConfig compatibility surface.
- Validate provider metadata before it is accepted by the router.
- Expand the test target to discover all test modules and include provider-registry checks.
- Correct the CI Make invocation and reduce the unit-test job token to read-only permissions.
- Add CodeQL analysis for Python and GitHub Actions on main-branch pushes and pull requests.
- Restrict POSIX bot-vault directory/file permissions to 0700/0600, use atomic writes, reject symlinks, and fail closed on corrupted vault data; encryption remains a documented limitation.

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
- **GUI**: Tkinter-based desktop GUI (`zcloud-gui.py`)
- **TUI**: Textual-based terminal UI (`zcloud-tui.py`)
- **Models Catalog**: 40 models across 14 providers with free/paid metadata
- **Provider Configuration**: provider.json for multi-provider API key management
- **CLI Executable**: `zcloud` shell script entry point

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
