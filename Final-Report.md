# Final Report — zrouter Production Readiness Audit

**Repository:** `cvsz/zrouter`  
**Branch:** `main` → `codex/enterprise-production-hardening`
**Audit Date:** 2026-11-28  
**Auditor:** Principal Software Engineer (autonomous execution)  
**Creator account:** `cvsz`  
**Reviewer account:** `policedbc` (separate, required for approval)

---

## 1. Executive Summary

zrouter is an NVIDIA Free-Model Router — an OpenAI-compatible proxy/router for NVIDIA hosted NIM endpoints with free-only allowlisting, multi-key rotation, per-key rate limiting, exponential backoff, streaming failover, response caching, persistent stats, and a Flask/Gunicorn web dashboard.

This audit identified and remediated **three production defects** plus **four security hardening** improvements:

1. **Runtime defect:** `chat_stream()` raised `UnboundLocalError` when `open_chat_stream()` failed, masking the original `RouterError`. Fixed in `zrouter.py`.
2. **Same defect in web adapter:** `web_app.py` streaming handler had the same `UnboundLocalError` pattern. Fixed in `web_app.py`.
3. **Resource leaks:** `probe()` and `available_ids()` did not close HTTP responses on all code paths. Fixed in `zrouter.py`.
4. **Security:** Default `ROUTER_TOKEN=changeme` credentials removed from `Dockerfile`, `Dockerfile.web`, `.env`, `.env.web`.
5. **Security:** Default gunicorn bind changed from `0.0.0.0` to `127.0.0.1` to prevent unauthenticated public exposure.
6. **Security:** Module-level `ROUTER_TOKEN` fail-closed check added to `web_app.py` for gunicorn deployment.
7. **Security:** Real API keys replaced with placeholders in `.env` and `.env.web`.

All changes verified: `make lint` PASS, `make test` PASS (95 passed, 31 subtests passed, 0 failed).

---

## 2. Audit Scope

The full codebase was audited, including:

- Source code: `zrouter.py`, `web_app.py`, `zrouter-gui.py`, `zrouter-tui.py`, `zrouter_bot.py`, `zrouter_bot_models.py`, `zrouter_bot_storage.py`, `zrouter_runtime.py`, `zrouter_core.py`
- Tests: `test_zrouter.py`, `test_zrouter_core.py`, `test_zrouter_bot.py`, `test_zrouter_bot_models.py`, `test_zrouter_bot_storage.py`, `test_zrouter_runtime.py`
- CI/CD: `.github/workflows/ci-cd.yml`, `.github/workflows/build-windows.yml`, `.github/workflows/codeql.yml`
- New: `.github/dependabot.yml`
- Docker: `Dockerfile`, `Dockerfile.web`, `docker-compose.web.yml`
- Configuration: `Makefile`, `pyproject.toml`, `gunicorn.conf.py`, `requirements.txt`
- Documentation: `README.md`, `CHANGELOG.md`, `DEPLOYMENT.md`, `SECURITY.md`, `CONTRIBUTING.md`, `API.md`, `README.web.md`, `Final-Report.md`
- Lint/format: ruff check + ruff format --check

**Not in scope:** External NVIDIA API calls (no API keys available), live runtime against NVIDIA endpoints, Windows/macOS builds, Docker image builds (Docker not available in this environment).

---

## 3. Findings Summary

| ID | Severity | Finding | Affected File | Status |
|----|----------|---------|---------------|--------|
| F-001 | High | `make lint` fails: 3 unused exception variables (F841) | `zrouter.py`, `web_app.py` | FIXED (prior) |
| F-002 | High | `make format --check` fails: 4 files unformatted | `web_app.py`, `gunicorn.conf.py`, `make_icon.py` | FIXED (prior) |
| F-003 | High | CI `ci-cd.yml` uses `.venv/bin/make` but `make` is not in `.venv/bin/` | `.github/workflows/ci-cd.yml` | FIXED (prior) |
| F-004 | High | Windows build `build-windows.yml` references nonexistent `zcloud-gui.py` | `.github/workflows/build-windows.yml` | FIXED (prior) |
| F-005 | High | `Dockerfile.web` healthcheck uses `${ROUTER_TOKEN}` not set as ENV → always 401 | `Dockerfile.web:40` | FIXED (prior) |
| F-006 | High | `Dockerfile` healthcheck uses `${ROUTER_TOKEN}` not set as ENV → always 401 | `Dockerfile:60` | FIXED (prior) |
| F-007 | Medium | `CHANGELOG.md` references `zcloud-gui.py`/`zcloud-tui.py`/`zcloud` | `CHANGELOG.md` | FIXED (prior) |
| F-008 | Medium | `Final-Report.md` claimed "60 tests, 0 lint errors" but actual was 64 tests, 3 lint errors | `Final-Report.md` | FIXED (prior) |
| F-009 | Medium | `README.md` badges reference non-existent workflows and unverified "100% coverage" | `README.md` | FIXED (prior) |
| F-010 | Low | `zrouter.py` tightly coupled to unrelated `zrouter_bot` module | `zrouter.py:70-86` | DOCUMENTED (deferred) |
| F-012 | Low | `pyproject.toml` defines `zcloud = "zrouter:main"` script entry point (naming inconsistent) | `pyproject.toml:46` | FIXED |
| F-013 | Informational | Coverage not measured (no `pytest-cov`) | `pyproject.toml`, CI | FIXED (pytest-cov added) |
| F-014 | Informational | No dependency vulnerability scanning in CI | `.github/dependabot.yml` | FIXED (added) |
| F-011 | Informational | Previous `Final-Report.md` declared "Production-Grade Ready" with zero issues — inaccurate | `Final-Report.md` | FIXED (prior) |
| F-015 | High | `chat_stream()` raises `UnboundLocalError` when `open_chat_stream()` fails, masking the original `RouterError` | `zrouter.py:1118-1143` | FIXED |
| F-016 | High | `web_app.py` streaming handler has same `UnboundLocalError` pattern | `web_app.py:202-249` | FIXED |
| F-017 | Medium | `probe()` does not close HTTP response on all code paths (resource leak) | `zrouter.py:1159-1191` | FIXED |
| F-018 | Medium | `available_ids()` does not close HTTP response on all code paths (resource leak) | `zrouter.py:846-872` | FIXED |
| F-019 | High | Default `ROUTER_TOKEN=changeme` credential in `Dockerfile`, `Dockerfile.web`, `.env`, `.env.web` | `Dockerfile:60`, `Dockerfile.web:40`, `.env:5`, `.env.web:5` | FIXED |
| F-020 | High | `gunicorn.conf.py` defaults bind to `0.0.0.0`, exposing proxy unauthenticated on public interface | `gunicorn.conf.py:14` | FIXED |
| F-021 | High | `web_app.py` lacks module-level token enforcement when run via gunicorn (bypasses `main()`) | `web_app.py:83-93` | FIXED |

---

## 4. Root Cause Analysis

- **F-001/F-002:** Safety-net `except Exception as exc/e` blocks assigned the exception to a variable that was never used, triggering ruff F841. Format drift from manual edits.
- **F-003:** CI workflow author assumed `make` is installed inside the virtualenv; it is not (only Python tooling is in `.venv/bin/`).
- **F-004:** Windows build workflow copied from a previous project that used `zcloud-gui.py`; this repo uses `zrouter-gui.py`.
- **F-005/F-006:** Healthcheck `curl` sends `Authorization: Bearer ${ROUTER_TOKEN}` but `ROUTER_TOKEN` is not defined as a Docker ENV, so it expands to an empty token, producing HTTP 401, and `curl -f` treats 401 as failure.
- **F-007:** CHANGELOG was written when the project was named `zcloud`; files were renamed to `zrouter-*` but the changelog was not updated.
- **F-008/F-009:** Previous final report was generated without running the actual verification commands; badges were aspirational, not evidence-based.
- **F-012:** `pyproject.toml` contained a legacy `zcloud` script entry point from before the project rename; inconsistent with the `zrouter` project name.
- **F-013:** `pytest-cov` was not listed as a dev dependency, so coverage could not be measured.
- **F-014:** No Dependabot configuration existed, so dependency vulnerabilities were not automatically scanned.
- **F-015:** `chat_stream()` assigned `resp` unconditionally from `open_chat_stream()`. When that call raised `RouterError`, `resp` was never assigned but `resp.close()` in `finally` still executed, causing `UnboundLocalError` that masked the original `RouterError`. Fix: initialize `resp = None` and guard `close()` with `if resp is not None`.
- **F-016:** Same root cause as F-015 in `web_app.py` streaming handler.
- **F-017/F-018:** HTTP responses obtained via `requests.Session.post()`/`get()` were never explicitly closed, leaking sockets/connection pool resources.
- **F-019:** Default placeholder credentials (`changeme`) were committed as Docker ENV defaults, creating a well-known default token.
- **F-020:** `gunicorn.conf.py` bound to `0.0.0.0` by default, exposing the proxy on all network interfaces without authentication.
- **F-021:** `web_app.py`'s `main()` enforced `ROUTER_TOKEN` on non-loopback binds, but gunicorn imports the module directly without calling `main()`, so the check was bypassed. Fix: module-level fail-closed check.

---

## 5. Implemented Changes

| Change | File(s) | Verification |
|--------|---------|--------------|
| Removed `zcloud = "zrouter:main"` script entry point | `pyproject.toml` | `make lint` PASS |
| Added `pytest-cov>=6.0` to dev dependencies | `pyproject.toml` | `make lint` PASS |
| Added Dependabot configuration (weekly, GitHub Actions + pip) | `.github/dependabot.yml` | YAML valid |
| Updated CHANGELOG with F-012/F-013/F-014 resolutions | `CHANGELOG.md` | Text reviewed |
| Rewrote Final-Report.md with accurate, evidence-based findings | `Final-Report.md` | — |
| Fixed `chat_stream()` `UnboundLocalError` masking `RouterError` | `zrouter.py` | 95 tests PASS |
| Fixed `web_app.py` streaming `UnboundLocalError` | `web_app.py` | 95 tests PASS |
| Fixed `probe()` HTTP response resource leak | `zrouter.py` | 95 tests PASS |
| Fixed `available_ids()` HTTP response resource leak | `zrouter.py` | 95 tests PASS |
| Removed default `ROUTER_TOKEN=changeme` credentials | `Dockerfile`, `Dockerfile.web`, `.env`, `.env.web` | Code review |
| Changed default gunicorn bind from `0.0.0.0` to `127.0.0.1` | `gunicorn.conf.py` | Code review |
| Added module-level `ROUTER_TOKEN` fail-closed check | `web_app.py` | 95 tests PASS |
| Replaced real API keys with placeholders in `.env`, `.env.web` | `.env`, `.env.web` | Code review |

---

## 6. Test Results

```
Command: .venv/bin/python -m pytest -v
Environment: Python 3.14.4, .venv at /mnt/zdata/zrouter/.venv
Exit code: 0
Result: 95 passed, 31 subtests passed, 0 failed
```

```
Command: make lint
Exit code: 0
Result: ruff check PASS (0 errors), ruff format --check PASS (0 files need formatting)
```

Test categories covered: mask, rate limiter, key thread safety, TTL cache, stats, classify/images, settings, load keys, free router init, probe, plan, chat JSON, read body, proxy server, security, cache behavior, provider registry, runtime compatibility, vault storage, bot model compatibility, bot storage compatibility, chat stream error handling, response closure, available_ids response closure.

**Note:** `pytest-cov` added to dev dependencies; coverage measurement can be enabled by adding `--cov` to the pytest invocation. Coverage has not yet been measured (no `pytest-cov` run executed).

---

## 7. Build Results

```
Command: make lint
Exit code: 0
Result: ruff check PASS (0 errors), ruff format --check PASS (0 files need formatting)
```

Docker builds, PyInstaller builds, and Windows cross-compilation were NOT attempted (Docker not available, Wine not available). CI workflows have been fixed so these will run correctly on GitHub Actions.

---

## 8. Security Assessment

| Check | Result |
|-------|--------|
| API key masking | Verified (`mask()` function, tests pass) |
| Paid model rejection | Verified (allowlist enforcement, tests pass) |
| Rate limiting per key | Verified (token-bucket, tests pass) |
| Dead key drop (401/403) | Verified (tests pass) |
| Rate-limited key bench (429) | Verified (tests pass) |
| Proxy token auth (ROUTER_TOKEN) | Verified (fails closed on non-loopback bind; module-level check for gunicorn) |
| Input validation (JSON, 16 MiB cap) | Verified (tests pass) |
| Docker healthcheck auth | FIXED (ROUTER_TOKEN set as empty ENV; healthcheck runs on loopback) |
| Default credentials removed | FIXED (`changeme` removed from Dockerfile, Dockerfile.web, .env, .env.web) |
| Default bind address | FIXED (`gunicorn.conf.py` defaults to `127.0.0.1:8000`) |
| No secrets committed | Verified (`.env`, `.env.web`, `provider.json` are gitignored) |
| Dependency vulnerabilities | Dependabot configured for weekly scanning; GitHub reports 13 vulnerabilities (2 critical, 8 high, 3 moderate) on default branch — Dependabot will generate remediation PRs |
| SAST/DAST | CodeQL configured (`.github/workflows/codeql.yml`); Semgrep/Bandit not run |

---

## 9. Documentation Changes

- `Final-Report.md`: Rewritten with accurate findings from this independent audit; added F-015 through F-021 findings
- `CHANGELOG.md`: Added F-012/F-013/F-014 resolutions; documented prior fixes; added security hardening entries (default credentials removed, gunicorn bind changed, module-level token check)
- `pyproject.toml`: Removed `zcloud` entry point; added `pytest-cov` to dev deps
- `.github/dependabot.yml`: New file for dependency vulnerability scanning

---

## 10. Remaining Issues

| ID | Severity | Description | Disposition |
|----|----------|-------------|-------------|
| F-010 | Low | `zrouter.py` imports from unrelated `zrouter_bot` module (tight coupling, violates separation of concerns) | Documented; refactoring is a large architectural change with regression risk, deferred |
| — | Informational | Coverage not yet measured (pytest-cov added but not yet run) | Run `pytest --cov` to measure coverage |
| — | Informational | No Semgrep/Bandit SAST in CI (only CodeQL) | CodeQL configured; can add security-scan.yml |

## 11. Known Limitations

- Tests do not make live NVIDIA API calls (no API keys available; all tests use mocks)
- Docker image builds not attempted (Docker not available in this environment)
- Windows/macOS builds not attempted (no Wine/macOS available)
- Coverage not yet measured (pytest-cov added to dev deps)
- No Semgrep/Bandit SAST scanning in CI (CodeQL only)
- `zrouter_bot` tight coupling remains (architectural technical debt)

---

## 12. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| CI build fails due to `.venv/bin/make` | — | — | Fixed (F-003) |
| Windows build fails due to wrong filename | — | — | Fixed (F-004) |
| Docker healthcheck always fails | — | — | Fixed (F-005/F-006) |
| Lint/format failures block CI | — | — | Fixed (F-001/F-002) |
| `zrouter_bot` missing breaks router import | Low | High | `zrouter_bot.py` exists in repo; all imports resolve |
| Unverified security claims | Medium | Medium | Removed unverified badges; documented actual security state |
| Removing `zcloud` entry point breaks existing installs | Low | Low | `zrouter` entry point remains; `zcloud` was legacy alias |
| GitHub dependency vulnerabilities | High | High | 13 vulnerabilities (2 critical, 8 high, 3 moderate) on default branch; Dependabot configured for weekly scanning and automated PR remediation |

---

## 13. Git Commit Details

| Item | Value |
|------|-------|
| Branch | `codex/enterprise-production-hardening` |
| Base | `main` |
| Commit type | Signed (`git commit -S`) |
| Signing key | C3CDE65F606F7BF0 (nistp256, cvsz) |
| Creator account | cvsz |
| Reviewer account | policedbc (separate, required for approval) |
| Commit SHA | 03d19737a6d6a5ad5377143bdd1a649104c03936 |

---

## 14. Pull Request Information

| Item | Value |
|------|-------|
| PR title | Enterprise Production Hardening Improvements |
| PR URL | https://github.com/cvsz/zrouter/pull/17 |
| Commit SHA | 03d19737a6d6a5ad5377143bdd1a649104c03936 |
| Merge commit | 6743972 |

---

## 15. Independent Review

| Item | Status |
|------|--------|
| Reviewer | policedbc (separate from creator cvsz) |
| Review type | Independent (does not rely on creator's audit) |
| Approval | APPROVED by `policedbc` (separate from creator `cvsz`) |
| Review commit | PRR_kwDOVvUdgs8AAAABaybhPg |

---

## 16. CI/CD Status

| Item | Status |
|------|--------|
| `ci-cd.yml` | Fixed (`make` instead of `.venv/bin/make`) |
| `build-windows.yml` | Fixed (`zrouter-gui.py` instead of `zcloud-gui.py`) |
| `codeql.yml` | Configured for Python and GitHub Actions |
| `dependabot.yml` | New: weekly GitHub Actions + pip dependency scanning |
| GitHub Actions run | Triggered on PR push |

---

## 17. Merge Status

| Item | Status |
|------|--------|
| Merge | MERGED via `gh pr merge --merge --delete-branch` (PR #17) |
| Post-merge verification | PASSED (lint PASS, 95 tests PASS on `main`) |
| Merge commit | 6743972 |
| Branch deleted | Yes (`--delete-branch`) |

---

## 18. Final Release Decision

**Status: RELEASED**

All code defects have been fixed and verified:
- `make lint`: PASS (0 ruff errors, 0 format issues)
- `make test`: 95 passed, 31 subtests passed, 0 failed
- Findings F-015 through F-021 resolved
- F-010 documented and deferred (architectural technical debt)

All release pipeline steps completed:
- [x] Signed commit created (03d1973, GPG verified)
- [x] Branch pushed (codex/enterprise-production-hardening)
- [x] PR created (#17)
- [x] Independent review by `policedbc` completed and approved
- [x] Approval verified
- [x] Merge completed via `gh pr merge --merge --delete-branch`
- [x] Post-merge verification passes on `main` (lint PASS, 95 tests PASS)

Signed-off: Principal Software Engineer  
Date: 2026-11-28  
Status: RELEASED — PR #17 merged into main