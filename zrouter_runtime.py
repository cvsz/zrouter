"""Thread-safe router runtime primitives shared by the public router module."""

from __future__ import annotations

import collections
import json
import logging
import os
import threading
import time
from typing import Any

log = logging.getLogger("nvrouter")
STATS_DIRTY_THRESHOLD = 20


def mask(key: str) -> str:
    """Return a masked representation of an API key for logging / display."""
    if not key:
        return "***"
    if len(key) <= 16:
        return "***"
    return key[:9] + "..." + key[-4:]


class RateLimiter:
    """Per-key token-bucket style rate limiter (requests per minute)."""

    def __init__(self, rpm: int) -> None:
        self.min_interval = 60.0 / max(rpm, 1)
        self.last = 0.0
        self.lock = threading.Lock()

    def wait(self) -> None:
        with self.lock:
            delay = self.last + self.min_interval - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            self.last = time.monotonic()


class Stats:
    """Per-model / per-key counters, persisted atomically as JSON."""

    def __init__(self, path: str | None = None) -> None:
        home = os.environ.get(
            "NVIDIA_ROUTER_HOME", os.path.expanduser("~/.nvidia_free_router")
        )
        self.path = path or os.path.join(home, "stats.json")
        self.lock = threading.Lock()
        self.dirty = 0
        self.data: dict[str, Any] = {"models": {}, "keys": {}}
        try:
            with open(self.path, encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    self.data = loaded
        except (OSError, ValueError):
            pass

    def rec(
        self, model: str, key_label: str, outcome: str, latency: float | None = None
    ) -> None:
        if outcome not in ("ok", "fail", "429"):
            raise ValueError(f"invalid outcome: {outcome!r}")
        with self.lock:
            m = self.data["models"].setdefault(
                model, {"ok": 0, "fail": 0, "429": 0, "lat_sum": 0.0}
            )
            k = self.data["keys"].setdefault(key_label, {"ok": 0, "fail": 0, "429": 0})
            m[outcome] += 1
            k[outcome] += 1
            if outcome == "ok" and latency is not None:
                m["lat_sum"] += latency
            self.dirty += 1
            if self.dirty >= STATS_DIRTY_THRESHOLD:
                self._save()

    def _save(self) -> None:
        try:
            directory = os.path.dirname(self.path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=1)
            os.replace(tmp, self.path)
            self.dirty = 0
        except OSError:
            log.exception("failed to persist stats to %s", self.path)

    def flush(self) -> None:
        with self.lock:
            if self.dirty:
                self._save()

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return json.loads(json.dumps(self.data))


class TTLCache:
    """Thread-safe TTL + LRU cache with bounded size."""

    def __init__(self, size: int, ttl: int) -> None:
        self.size = max(size, 0)
        self.ttl = max(ttl, 0)
        self.d: collections.OrderedDict[str, tuple[float, Any]] = (
            collections.OrderedDict()
        )
        self.lock = threading.Lock()

    def get(self, k: str) -> Any | None:
        with self.lock:
            v = self.d.get(k)
            if not v:
                return None
            expiry, val = v
            if time.time() > expiry:
                del self.d[k]
                return None
            self.d.move_to_end(k)
            return val

    def put(self, k: str, val: Any) -> None:
        if self.ttl <= 0:
            return
        with self.lock:
            self.d[k] = (time.time() + self.ttl, val)
            self.d.move_to_end(k)
            while len(self.d) > self.size:
                self.d.popitem(last=False)
