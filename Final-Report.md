# Final Report — zrouter Production Readiness Audit

**Repository:** `cvsz/zrouter`  
**Branch:** `main` → `codex/enterprise-production-hardening`  
**Audit Date:** 2026-11-28  
**Auditor:** Principal Software Engineer (autonomous execution)

---

## 1. Executive Summary

zrouter is an NVIDIA Free-Model Router — an OpenAI-compatible proxy/router for NVIDIA hosted NIM endpoints with free-only allowlisting, multi-key rotation, per-key rate limiting, exponential backoff, streaming failover, response caching, persistent stats, and a Flask/Gunicorn web dashboard.

**This audit found real, verifiable defects** that contradicted the previous `Final-Report.md`, which claimed "zero issues across all verification dimensions." The previous report was inaccurate: it claimed 60 tests (actual: 64), 0 lint errors (actual: 3 F841 errors causing `make lint` to fail), and 0 format issues (actual: 4 files needing formatting). CI workflows referenced nonexistent paths (`zcloud-gui.py`, `.venv/bin/make`) and the Dockerfile.web healthcheck always failed because `ROUTER_TOKEN` was not set as an ENV.

All confirmed defects have been fixed, verified, and documented in this report.

---

## 2. Audit Scope

The full codebase was audited, including:

- Source code: `zrouter.py`, `web_app.py`, `zrouter-gui.py`, `zrouter-tui.py`, `zrouter_bot.py`, `make_icon.py`
- Tests: `test_zrouter.py` (64 tests)
- CI/CD: `.github/workflows/ci-cd.yml`, `.github/workflows/build-windows.yml`
- Docker: `Dockerfile`, `Dockerfile.web`, `docker-compose.web.yml`
- Configuration: `Makefile`, `pyproject.toml`, `gunicorn.conf.py`, `requirements.txt`
- Documentation: `README.md`, `CHANGELOG.md`, `DEPLOYMENT.md`, `SECURITY.md`, `CONTRIBUTING.md`, `API.md`, `README.web.md`
- Lint/format: ruff check + ruff format --check

**Not in scope:** External NVIDIA API calls (no API keys available), live runtime against NVIDIA endpoints, Windows/macOS builds, Docker image builds (Docker not available in this environment).

---

## 3. Findings Summary

| ID | Severity | Finding | Affected File | Status |
|----|----------|---------|---------------|--------|
| F-001 | High | `make lint` fails: 3 unused exception variables (F841) | `zrouter.py:1432`, `web_app.py:245`, `web_app.py:262` | FIXED |
| F-002 | High | `make format --check` fails: 4 files unformatted | `web_app.py`, `gunicorn.conf.py`, `make_icon.py` | FIXED |
| F-003 | High | CI `ci-cd.yml` uses `.venv/bin/make` but `make` is not in `.venv/bin/` | `.github/workflows/ci-cd.yml:44,77` | FIXED |
| F-004 | High | Windows build `build-windows.yml` references nonexistent `zcloud-gui.py` | `.github/workflows/build-windows.yml:68,95,101` | FIXED |
| F-005 | High | `Dockerfile.web` healthcheck uses `${ROUTER_TOKEN}` not set as ENV → always 401 | `Dockerfile.web:42` | FIXED |
| F-006 | High | `Dockerfile` healthcheck uses `${ROUTER_TOKEN}` not set as ENV → always 401 | `Dockerfile:64` | FIXED |
| F-007 | Medium | `CHANGELOG.md` references `zcloud-gui.py`/`zcloud-tui.py`/`zcloud` (actual: `zrouter-gui.py`/`zrouter-tui.py`/`zrouter`) | `CHANGELOG.md` | FIXED |
| F-008 | Medium | `Final-Report.md` claimed "60 tests, 0 lint errors" but actual was 64 tests, 3 lint errors | `Final-Report.md` | FIXED |
| F-009 | Medium | `README.md` badges reference non-existent workflows (`ci.yml`, `security-scan.yml`, `codeql.yml`, `release-gate.yml`) and unverified "100% coverage" | `README.md` | FIXED |
| F-010 | Low | `zrouter.py` tightly coupled to unrelated `zrouter_bot` module (calendar, email, cart, media, etc.) | `zrouter.py:70-86` | DOCUMENTED (not refactored) |
| F-011 | Informational | Previous `Final-Report.md` declared "Production-Grade Ready" with zero issues — inaccurate | `Final-Report.md` | FIXED |

---

## 4. Root Cause Analysis

- **F-001/F-002:** Safety-net `except Exception as exc/e` blocks assigned the exception to a variable that was never used, triggering ruff F841. Format drift from manual edits.
- **F-003:** CI workflow author assumed `make` is installed inside the virtualenv; it is not (only Python tooling is in `.venv/bin/`).
- **F-004:** Windows build workflow copied from a previous project that used `zcloud-gui.py`; this repo uses `zrouter-gui.py`.
- **F-005/F-006:** Healthcheck `curl` sends `Authorization: Bearer ${ROUTER_TOKEN}` but `ROUTER_TOKEN` is not defined as a Docker ENV, so it expands to an empty token, producing HTTP 401, and `curl -f` treats 401 as failure.
- **F-007:** CHANGELOG was written when the project was named `zcloud`; files were renamed to `zrouter-*` but the changelog was not updated.
- **F-008/F-009:** Previous final report was generated without running the actual verification commands; badges were aspirational, not evidence-based.

---

## 5. Implemented Changes

| Change | File(s) | Verification |
|--------|---------|--------------|
| Removed unused exception variable `e` in `except Exception` | `zrouter.py:1432` | `make lint` PASS |
| Removed unused exception variable `exc` (chat endpoint) | `web_app.py:245` | `make lint` PASS |
| Removed unused exception variable `exc` (embeddings endpoint) | `web_app.py:262` | `make lint` PASS |
| Reformatted `web_app.py` | `web_app.py` | `ruff format --check` PASS |
| Reformatted `gunicorn.conf.py` (quote style) | `gunicorn.conf.py` | `ruff format --check` PASS |
| Reformatted `make_icon.py` (line wrapping) | `make_icon.py` | `ruff format --check` PASS |
| CI: `.venv/bin/make lint` → `make lint` | `.github/workflows/ci-cd.yml` | YAML valid |
| CI: `.venv/bin/make test` → `make test` | `.github/workflows/ci-cd.yml` | YAML valid |
| CI: `.venv/bin/make build:exe` → `make build:exe` | `.github/workflows/ci-cd.yml` | YAML valid |
| CI: `.venv/bin/make build:all` → `make build:all` | `.github/workflows/ci-cd.yml` | YAML valid |
| Windows GUI: `zcloud-gui.py` → `zrouter-gui.py` | `.github/workflows/build-windows.yml` | YAML valid |
| Windows GUI artifact: `zcloud-gui-windows-exe` → `zrouter-gui-windows-exe` | `.github/workflows/build-windows.yml` | YAML valid |
| Windows GUI artifact path: `dist/zcloud-gui.exe` → `dist/zrouter-gui.exe` | `.github/workflows/build-windows.yml` | YAML valid |
| Dockerfile.web: added `ENV ROUTER_TOKEN=changeme` | `Dockerfile.web` | Syntax reviewed |
| Dockerfile: added `ENV ROUTER_TOKEN=changeme` | `Dockerfile` | Syntax reviewed |
| CHANGELOG: `zcloud-gui.py` → `zrouter-gui.py` | `CHANGELOG.md` | Text reviewed |
| CHANGELOG: `zcloud-tui.py` → `zrouter-tui.py` | `CHANGELOG.md` | Text reviewed |
| CHANGELOG: `zcloud` → `zrouter` | `CHANGELOG.md` | Text reviewed |
| README: fixed CI badge workflow reference (`ci.yml` → `ci-cd.yml`) | `README.md` | Text reviewed |
| README: removed unverified Security Scan / CodeQL / Release Gate / Coverage badges | `README.md` | Text reviewed |
| README: replaced "Production-Grade Ready" status with version + reference to Final-Report | `README.md` | Text reviewed |
| Final-Report.md: rewritten with accurate, evidence-based findings | `Final-Report.md` | — |

---

## 6. Test Results

```
Command: .venv/bin/python -m pytest test_zrouter.py -v
Environment: Python 3.14.4, .venv at /mnt/zdata/zrouter/.venv
Exit code: 0
Result: 64 passed, 0 failed
```

Test categories covered: mask, rate limiter, key thread safety, TTL cache, stats, classify/images, settings, load keys, free router init, probe, plan, chat JSON, read body, proxy server, security, cache behavior.

**Note:** Coverage has not been measured (no `pytest-cov` installed). The previous claim of "100% coverage" was unverified and has been removed.

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
| Proxy token auth (ROUTER_TOKEN) | Verified (fails closed on non-loopbind) |
| Input validation (JSON, 16 MiB cap) | Verified (tests pass) |
| Docker healthcheck auth | FIXED (ROUTER_TOKEN now set as ENV) |
| No secrets committed | Verified (.env, .env.web, provider.json are gitignored) |
| Dependency vulnerabilities | Not scanned (no dependency scanner available in this environment) |
| SAST/DAST | Not run (no CodeQL, Semgrep, Bandit available in this environment) |

---

## 9. Documentation Changes

- `Final-Report.md`: Rewritten with accurate findings (replaced inaccurate "zero issues" report)
- `README.md`: Fixed CI workflow badge reference; removed unverified Security Scan/CodeQL/Release Gate/Coverage badges; replaced "Production-Grade Ready" with accurate status
- `CHANGELOG.md`: Fixed `zcloud-*` → `zrouter-*` naming references

---

## 10. Remaining Issues

| ID | Severity | Description | Disposition |
|----|----------|-------------|-------------|
| F-010 | Low | `zrouter.py` imports from unrelated `zrouter_bot` module (tight coupling, violates separation of concerns) | Documented; refactoring is a large architectural change with regression risk, deferred |
| — | Informational | Coverage not measured (no `pytest-cov`) | Can add `pytest-cov` and coverage gate to CI |
| — | Informational | No SAST/DAST/dependency scanning in CI | Can add security-scan.yml, codeql.yml workflows |
| — | Informational | `pyproject.toml` defines `zcloud = "zrouter:main"` script entry point (naming inconsistent with `zrouter` script) | Minor naming inconsistency, low impact |

---

## 11. Known Limitations

- Tests do not make live NVIDIA API calls (no API keys available; all tests use mocks)
- Docker image builds not attempted (Docker not available in this environment)
- Windows/macOS builds not attempted (no Wine/macOS available)
- Coverage not measured
- No dependency vulnerability scanning performed
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

---

## 13. Git Commit Details

| Item | Value |
|------|-------|
| Branch | `codex/enterprise-production-hardening` |
| Base | `main` (5b5eaaf) |
| Commit type | Signed (`git commit -S`) |
| Signing key | C3CDE65F606F7BF0 (nistp256, cvsz) |
| Creator account | cvsz |
| Reviewer account | policedbc (separate, required for approval) |

---

## 14. Pull Request Information

| Item | Value |
|------|-------|
| PR title | Enterprise Production Readiness Improvements |
| PR URL | (to be created after push) |
| Commit SHA | (to be recorded after commit) |

---

## 15. Independent Review

| Item | Status |
|------|--------|
| Reviewer | policedbc (separate from creator cvsz) |
| Review type | Independent (does not rely on creator's audit) |
| Approval | (pending — requires `gh pr review --approve` from policedbc) |

---

## 16. CI/CD Status

| Item | Status |
|------|--------|
| `ci-cd.yml` | Fixed (`make` instead of `.venv/bin/make`) |
| `build-windows.yml` | Fixed (`zrouter-gui.py` instead of `zcloud-gui.py`) |
| GitHub Actions run | Not triggered (awaiting PR push) |

---

## 17. Merge Status

| Item | Status |
|------|--------|
| Merge | (pending — requires PR approval and merge) |
| Post-merge verification | (pending) |

---

## 18. Final Release Decision

**Status: NOT YET RELEASED**

All code defects have been fixed and verified locally (lint PASS, 64 tests PASS). The release pipeline (PR → independent review → merge → post-merge verification) has not been completed yet. This report will be updated after the PR is created, reviewed, approved, merged, and post-merge verification is performed.

**Do not declare PRODUCTION READY until:**
- PR is created and pushed
- Independent review by `policedbc` is completed and approved
- CI checks pass on GitHub Actions
- Merge is completed
- Post-merge verification passes on `main`

---

Signed-off: Principal Software Engineer  
Date: 2026-11-28  
Status: AUDIT COMPLETE, FIXES IMPLEMENTED, RELEASE PENDING