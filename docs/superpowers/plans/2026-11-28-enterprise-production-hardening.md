# Enterprise Production Hardening Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all verified issues in zrouter (lint errors, format issues, CI/CD bugs, Docker healthcheck bug, documentation inaccuracies) and produce a signed, reviewed, merged production-ready release.

**Architecture:** Python Flask/Gunicorn router (zrouter.py + web_app.py) with pytest tests, ruff lint/format, GitHub Actions CI/CD. Fixes are surgical: remove unused exception variables, reformat files, fix CI make paths, fix Windows GUI filename, add ROUTER_TOKEN ENV to Dockerfiles, correct documentation.

**Tech Stack:** Python 3.14, Flask, Gunicorn, pytest, ruff, GitHub Actions, GPG signed commits.

**Spec:** This plan implements the Enterprise Software Engineering Master Prompt (audit → fix → test → document → commit → PR → review → merge → verify → report).

## Global Constraints
- No new Git worktree
- No `git reset --hard`, `git clean -fd`, force push, `git checkout .`
- Preserve existing user changes and the pre-existing stash
- Signed commits required (`git commit -S`)
- GPG signing key: C3CDE65F606F7BF0 (commit.gpgsign = true)
- Creator account: cvsz; Reviewer account: policedbc (separate accounts)
- Branch: `codex/enterprise-production-hardening` from main
- No fake test results, no fabricated approvals

## Review Focus (failure modes not directly covered by task tests)
1. `.venv/bin/make` path in CI — make is not in venv → CI job fails
2. `zcloud-gui.py` filename in Windows workflow — file doesn't exist → build fails
3. Dockerfile.web healthcheck with unset ROUTER_TOKEN → 401 → healthcheck always fails
4. Unused exception variables → lint failure (F841)
5. CHANGELOG.md references zcloud-gui.py/zcloud-tui.py that don't exist

---

### Task 1: Fix ruff lint errors (3 unused exception variables)

**Files:**
- Modify: `zrouter.py:1432` — `except Exception as e:` → `except Exception:`
- Modify: `web_app.py:245` — `except Exception as exc:` → `except Exception:`
- Modify: `web_app.py:262` — `except Exception as exc:` → `except Exception:`

**Interfaces:** None (syntactic cleanup only).

- [ ] **Step 1:** Apply the 3 edits
- [ ] **Step 2:** Run `make lint` → Expected: PASS (exit 0)
- [ ] **Step 3:** Commit lint fixes

### Task 2: Fix ruff format issues (4 files)

**Files:**
- Modify: `web_app.py`, `gunicorn.conf.py`, `make_icon.py` (format via ruff)

**Interfaces:** None.

- [ ] **Step 1:** Run `.venv/bin/python -m ruff format web_app.py gunicorn.conf.py make_icon.py`
- [ ] **Step 2:** Run `make lint` (includes format check) → Expected: PASS
- [ ] **Step 3:** Commit format fixes

### Task 3: Fix CI/CD workflow bugs

**Files:**
- Modify: `.github/workflows/ci-cd.yml` — `.venv/bin/make lint` → `make lint`, `.venv/bin/make test` → `make test`
- Modify: `.github/workflows/build-windows.yml` — `zcloud-gui.py` → `zrouter-gui.py`

**Interfaces:** None.

- [ ] **Step 1:** Apply both workflow edits
- [ ] **Step 2:** Verify YAML syntax is valid
- [ ] **Step 3:** Commit CI fixes

### Task 4: Fix Dockerfile.web healthcheck (ROUTER_TOKEN not set)

**Files:**
- Modify: `Dockerfile.web` — add `ENV ROUTER_TOKEN` or fix healthcheck to not require token
- Modify: `Dockerfile` — same healthcheck issue

**Interfaces:** None.

- [ ] **Step 1:** Add `ENV ROUTER_TOKEN` placeholder or adjust healthcheck
- [ ] **Step 2:** Commit Dockerfile fixes

### Task 5: Fix documentation inconsistencies

**Files:**
- Modify: `CHANGELOG.md` — `zcloud-gui.py` → `zrouter-gui.py`, `zcloud-tui.py` → `zrouter-tui.py`, `zcloud` → `zrouter`
- Modify: `Final-Report.md` — accurate findings (64 tests not 60, 3 lint errors not 0, etc.)
- Modify: `README.md` — remove unverified badge claims (100% coverage, all passing)

**Interfaces:** None.

- [ ] **Step 1:** Apply all doc edits
- [ ] **Step 2:** Commit doc fixes

### Task 6: Verify full quality gate

**Files:** None (verification only).

- [ ] **Step 1:** Run `make lint` → PASS
- [ ] **Step 2:** Run `make test` → 64 tests PASS
- [ ] **Step 3:** Run `git status --short`, `git diff --cached` to review staged changes
- [ ] **Step 4:** Verify no secrets in staged changes

### Task 7: Git operations (branch, commit, push, PR)

**Files:** None.

- [ ] **Step 1:** `gh auth switch -u cvsz`; `gh auth status`
- [ ] **Step 2:** Create branch `codex/enterprise-production-hardening` from main
- [ ] **Step 3:** Stage all fixed files; `git status --short`; `git diff --cached`
- [ ] **Step 4:** `git commit -S -m "..."` (signed)
- [ ] **Step 5:** `git verify-commit HEAD`
- [ ] **Step 6:** Push branch
- [ ] **Step 7:** `gh pr create` with full description
- [ ] **Step 8:** Record PR URL and commit SHA

### Task 8: Independent review (policedbc)

- [ ] **Step 1:** `gh auth switch -u policedbc`; `gh auth status`
- [ ] **Step 2:** `gh pr diff`, `gh pr checks`
- [ ] **Step 3:** Independent code review; `gh pr review --approve` or `--request-changes`

### Task 9: Merge and post-merge verification (cvsz)

- [ ] **Step 1:** `gh auth switch -u cvsz`
- [ ] **Step 2:** Verify CI passed, approval present, no conflicts
- [ ] **Step 3:** `gh pr merge --merge --delete-branch`
- [ ] **Step 4:** Fetch remote, update local main, verify merge commit
- [ ] **Step 5:** Run `make lint` and `make test` on main

### Task 10: Final Report

- [ ] **Step 1:** Update `Final-Report.md` with actual results
- [ ] **Step 2:** Commit final report if needed
- [ ] **Step 3:** Deliver final response with PASS/FAIL/BLOCKED statuses