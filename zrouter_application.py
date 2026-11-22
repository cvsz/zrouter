"""Router application service: routing, provider failover, streaming, and diagnostics."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import logging
import re
import threading
import time
from collections.abc import Iterator
from typing import Any

import requests

from zrouter_config import (
    CFG,
    MODEL_LIST_TTL,
    PAIR_BACKOFF_CAP,
    RETRY_AFTER_CAP,
    Key,
    load_keys,
)
from zrouter_contracts import RouterError
from zrouter_runtime import RateLimiter, Stats, TTLCache

log = logging.getLogger("nvrouter")


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
