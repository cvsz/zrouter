# Validation Results

Evidence for the refactor implementation is tied to the exact tested code commit.

## Refactor implementation

- Base branch: `main`
- Feature branch: `refactor/openmausbot-router-architecture`
- Validated code commit: `9df4fc92ab3d7fb46da066dd49c80120ba68fc40`
- Environment: GitHub-hosted Ubuntu runner, Python 3.14.10
- Local execution: **NOT RUN**; validation was performed by GitHub Actions.

## Automated results

| Gate | Result | Evidence |
|---|---|---|
| Ruff lint | **PASS** | [CI/CD run](https://github.com/cvsz/zrouter/actions/runs/44236819938) |
| Ruff format | **PASS** | [CI/CD run](https://github.com/cvsz/zrouter/actions/runs/44236819938) |
| Pytest | **PASS — 82 tests, 7 subtests** | [CI/CD run](https://github.com/cvsz/zrouter/actions/runs/44236819938) |
| PyInstaller Linux CLI | **PASS** | [Build artifact run](https://github.com/cvsz/zrouter/actions/runs/44236819938) |
| CodeQL: Python + GitHub Actions | **PASS** | [CodeQL run](https://github.com/cvsz/zrouter/actions/runs/44236819945) |
| Release job | **SKIPPED intentionally** | No release authorization was requested |

## Not verified

- Docker image build and runtime smoke test
- Windows executable build
- Live NVIDIA NIM requests, provider failover against real upstreams, and end-to-end streaming cancellation
- GUI/TUI runtime behavior on desktop platforms
- Production deployment, load testing, and external provider pricing verification

## Security limitations

- The initial Phase 2 implementation used plaintext JSON with restrictive POSIX permissions. Phase 3 replaces active vault storage with a native OS keyring; legacy files require explicit migration and historical filesystem blocks/backups are not guaranteed to be securely erased.
- Model discovery does not prove pricing. New models remain `free=false` and `pricing_status=unverified` until explicitly curated.
- Remote plaintext HTTP provider endpoints are rejected; only loopback HTTP is allowed.

## Phase 2 — router and bot module extraction

- Extract 3 bot enums and 17 serializable domain models (20 public types) into `zrouter_bot_models.py`.
- Extract `Vault`, `Memory`, and bot-home storage paths into `zrouter_bot_storage.py`.
- Extract router `RateLimiter`, `Stats`, `TTLCache`, and `mask` into `zrouter_runtime.py`.
- Compatibility: `zrouter_bot.py` re-exports previous model names, storage classes, and path constants; `zrouter.py` re-exports previous runtime primitive names.
- Packaging: include the new modules in `pyproject.toml`, Docker runtime/web images, Makefile lint/source bundles, and PyInstaller dependency discovery.
- Regression coverage: test compatibility import identity, model serialization, and bot memory persistence; existing rate limiter, stats, cache, and masking tests remain active.
- Validated code commit: `cb144909d66ff9a4fedec27bd8874d08ee8ebb2c`.
- [CI/CD run](https://github.com/cvsz/zrouter/actions/runs/44247817520): **PASS** — Ruff lint/format, **88 tests passed and 31 subtests passed**, Linux PyInstaller executable build, artifact upload.
- [CodeQL run](https://github.com/cvsz/zrouter/actions/runs/44247817598): **PASS** — Python and GitHub Actions.
- Local execution: not run in this session; validation was performed by GitHub Actions.

## Evidence policy

The automated results above apply to the validated code commit listed above. Any later code change requires a new validation run. Documentation-only updates do not change the tested runtime code.

## Phase 3 — HTTP boundary extraction and vault hardening

- Extract HTTP parsing, bearer authentication, SSE response ownership, and server lifecycle into `zrouter_http.py`; retain `zrouter.py` compatibility wrappers.
- Move `RouterError` and the 16 MiB request cap into `zrouter_contracts.py`.
- Replace plaintext vault values with native OS keyring storage. The JSON index stores metadata only.
- Reject unsupported/insecure keyring implementations and fail closed when no native credential store is available.
- Detect legacy plaintext vaults; migration requires an explicit `confirm=True` call and does not claim secure erasure of historical filesystem blocks or backups.
- Add keyring dependency and update packaging/container source manifests.
- Validated runtime code commit: `03e8e2e1fbc0790e0665456a0f9c014ac5ec12ed`.
- [CI/CD run](https://github.com/cvsz/zrouter/actions/runs/45052948407): **PASS** — Ruff lint/format, **103 tests passed and 31 subtests passed**, Linux PyInstaller executable build, and artifact upload.
- [CodeQL run](https://github.com/cvsz/zrouter/actions/runs/45052948410): **PASS** — Python and GitHub Actions.
- [Linux executable artifact](https://github.com/cvsz/zrouter/actions/runs/45052948407/artifacts/14766446868).
- Local clone/test execution was unavailable because this environment could not resolve GitHub; the CI runner performed the validation above.
- Docker image build/runtime, Windows/macOS keyring behavior, Linux SecretService integration, live NVIDIA NIM, streaming client-disconnect behavior, load behavior, and production deployment remain unverified.


## Phase 4 — application extraction and runtime acceptance

Validated PR head: `d19d6e4d561cace01c077fadb5d2cbb59faa2114`.

### Completed implementation
- Extracted configuration/provider loading into `zrouter_config.py`, curated model catalog into `zrouter_catalog.py`, router application into `zrouter_application.py`, and CLI dispatch into `zrouter_cli.py`.
- Retained `zrouter.py` as the compatibility facade and executable entry point; regression tests verify import identity and CLI command parsing.
- Added bounded, regular-file-only, no-symlink support for `ROUTER_TOKEN_FILE` and `NVIDIA_KEYS_FILE`; Docker Compose injects API keys and router tokens through read-only secret mounts.
- Added minimal public `/livez`; operational and inference endpoints remain bearer-authenticated.
- Corrected both Docker images: complete module manifests, production dependency manifests, non-root UID/GID 10001, writable application home, named persistence volumes, loopback-only Compose publishing, and Docker liveness checks.
- Added end-to-end HTTP tests for stream client disconnect cleanup and 96 concurrent authenticated health requests.
- Added Docker image build/runtime smoke checks for both proxy and web images using synthetic credentials and mounted secret files only.
- Added native credential-store integration matrix for Linux SecretService, macOS Keychain, and Windows Credential Locker.
- Added a manual-only NVIDIA NIM smoke workflow and script: one synthetic prompt, no retries, fixed official HTTPS endpoint, curated model allowlist, bounded timeout, suppressed response body, and typed authorization.
- Added deployment, vault migration, backup, rollback, and production acceptance runbook.

### CI evidence
- [CI/CD run #136](https://github.com/cvsz/zrouter/actions/runs/45057596330): **PASS** — Ruff lint/format, **117 tests passed, 1 skipped, 31 subtests passed**, Linux PyInstaller build, and artifact upload.
- [Runtime Validation run #136](https://github.com/cvsz/zrouter/actions/runs/45057596283): **PASS** — both Docker images built and ran; Compose secret configuration validated; router and web liveness/authenticated health checks passed using synthetic test credentials.
- Native keyring matrix in Runtime Validation: **PASS** — Linux SecretService, macOS Keychain, and Windows Credential Locker. Each platform performed a synthetic secret round-trip and cleanup.
- [CodeQL run #136](https://github.com/cvsz/zrouter/actions/runs/45057596317): **PASS** — Python and GitHub Actions.
- [Linux executable artifact](https://github.com/cvsz/zrouter/actions/runs/45057596330/artifacts/14768296607).

### Explicitly not executed / residual limits
- **Live NVIDIA NIM request:** not executed. The workflow is manual-only and requires the repository secret `NVIDIA_NIM_API_KEY` plus typed authorization. The catalog's `free: true` flag is not a billing guarantee; the operator must verify current pricing/quotas before triggering it.
- **Production deployment, migration, and rollback:** not executed. No zrouter target host/environment or operator access was provided. The runbook records preconditions and the backward-compatibility boundary.
- The default Docker images do not mount a host-native credential store; Vault secret CRUD intentionally fails closed inside those containers.
- The streaming-disconnect and concurrency tests use a synthetic in-process router, not a live NVIDIA stream or production traffic. The load test is bounded to 96 concurrent health requests; it is not a throughput/SLO benchmark.
- Docker image runtime smoke tests validate startup, file-secret reads, liveness, and authentication; they do not send inference requests to NVIDIA.
- Local clone/test execution was unavailable in this environment; the recorded GitHub Actions runners performed the validation above.

No merge, release, tag, production migration, or deployment was performed.
