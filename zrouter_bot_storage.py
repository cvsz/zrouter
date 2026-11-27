"""Bot persistence primitives and local storage paths."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from zrouter_bot_models import VaultEntry

log = logging.getLogger("zrouter-bot")

HOME = Path.home()
BOT_HOME = HOME / ".zrouter_bot"
BOT_HOME.mkdir(mode=0o700, parents=True, exist_ok=True)
if os.name == "posix":
    os.chmod(BOT_HOME, 0o700)

VAULT_FILE = BOT_HOME / "vault.json"
MEMORY_FILE = BOT_HOME / "memory.json"


class Vault:
    """Local JSON credential store; contents are plaintext and rely on file permissions."""

    def __init__(self, path: Path = VAULT_FILE) -> None:
        self.path = path
        self._entries: dict[str, VaultEntry] = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if self.path.is_symlink():
            raise RuntimeError("refusing to read a symlinked vault file")
        if not self.path.exists():
            self._entries = {}
            return
        try:
            if os.name == "posix":
                os.chmod(self.path, 0o600)
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                raise TypeError("vault root must be a JSON array")
            self._entries = {entry["id"]: VaultEntry.from_dict(entry) for entry in data}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            log.exception("Vault could not be loaded; refusing to overwrite it")
            raise RuntimeError(
                "vault file is unreadable or corrupt; refusing to start with an empty vault"
            ) from exc

    def _save(self) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name == "posix":
            os.chmod(self.path.parent, 0o700)
        tmp = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(
                    [entry.to_dict() for entry in self._entries.values()],
                    f,
                    indent=2,
                )
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
            if os.name == "posix":
                os.chmod(self.path, 0o600)
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass
            raise

    def list(self) -> list[VaultEntry]:
        with self._lock:
            return list(self._entries.values())

    def get(self, entry_id: str) -> VaultEntry | None:
        with self._lock:
            return self._entries.get(entry_id)

    def add(self, entry: VaultEntry) -> VaultEntry:
        with self._lock:
            self._entries[entry.id] = entry
            self._save()
            return entry

    def update(self, entry_id: str, value: dict[str, Any]) -> VaultEntry | None:
        with self._lock:
            entry = self._entries.get(entry_id)
            if entry is None:
                return None
            entry.value = value
            entry.updated_at = time.time()
            self._save()
            return entry

    def delete(self, entry_id: str) -> bool:
        with self._lock:
            if entry_id not in self._entries:
                return False
            del self._entries[entry_id]
            self._save()
            return True


# --------------------------------------------------------------------------- #
# Memory — per-bot context persistence
# --------------------------------------------------------------------------- #
class Memory:
    """Simple key/value memory store persisted to disk."""

    def __init__(self, path: Path = MEMORY_FILE) -> None:
        self.path = path
        self._mem: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._mem = {}
            return
        try:
            with self.path.open("r", encoding="utf-8") as f:
                self._mem = json.load(f)
        except (OSError, ValueError):
            log.exception("Failed to load memory; starting empty")
            self._mem = {}

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(self._mem, f, indent=2)
        os.replace(tmp, self.path)

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._mem.get(key, default)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._mem[key] = value
            self._save()

    def delete(self, key: str) -> bool:
        with self._lock:
            if key not in self._mem:
                return False
            del self._mem[key]
            self._save()
            return True

    def all(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._mem)


# --------------------------------------------------------------------------- #
