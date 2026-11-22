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

- Extract configuration/provider loading into `zrouter_config.py`, model catalog into `zrouter_catalog.py`, router application into `zrouter_application.py`, and CLI dispatch into `zrouter_cli.py`.
- Preserve `zrouter.py` as the compatibility facade and executable entry point; add import-identity and CLI parser regression tests.
- Add bounded no-follow `ROUTER_TOKEN_FILE` support and Docker Compose file-secret injection for provider keys and router tokens.
- Add minimal unauthenticated `/livez`; retain bearer authentication on operational and inference endpoints.
- Correct runtime/web Docker module manifests, provision non-root writable home directories, add named persistent volumes, and split runtime/web dependency manifests.
- Add stream-disconnect and bounded concurrent health-request tests.
- Add Docker image build/runtime smoke workflow using synthetic credentials only.
- Add native keyring integration matrix for Linux SecretService, macOS Keychain, and Windows Credential Locker.
- Add a manual, one-request NVIDIA NIM smoke workflow with typed authorization, curated model validation, official HTTPS endpoint pinning, bounded timeout, and no retries.
- Code extraction and new runtime workflows are committed on the PR branch. Automated results for the current head are **PENDING**; do not reuse earlier Phase 3 CI results as evidence for this phase.
- Native keyring platform results, Docker build/runtime results, and the exact current-head CI/CodeQL runs must be recorded after completion.
- Real NVIDIA NIM execution is **BLOCKED** until an authorized `NVIDIA_NIM_API_KEY` repository secret is configured and an operator manually triggers the gated workflow.
- Production deployment, migration, and rollback are **NOT VERIFIED** because no zrouter target host/environment has been identified or accessed. No production mutation was performed.
- Docker containers do not mount native OS credential stores; vault secret CRUD intentionally remains unavailable in the default container runtime.
- Legacy vault migration is not backward-compatible with pre-keyring releases. After migration, prefer forward recovery; do not blindly roll back to plaintext-vault code.
