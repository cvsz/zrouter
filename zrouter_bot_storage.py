"""Bot persistence primitives with OS-backed credential storage."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Protocol

from zrouter_bot_models import VaultEntry

log = logging.getLogger("zrouter-bot")

HOME = Path.home()
BOT_HOME = HOME / ".zrouter_bot"
BOT_HOME.mkdir(mode=0o700, parents=True, exist_ok=True)
if os.name == "posix":
    os.chmod(BOT_HOME, 0o700)

VAULT_FILE = BOT_HOME / "vault.json"
MEMORY_FILE = BOT_HOME / "memory.json"
KEYRING_SERVICE = "zrouter.bot.vault.v1"


class VaultBackend(Protocol):
    """Secret backend contract. Implementations must protect values at rest."""

    def get(self, entry_id: str) -> str | None: ...
    def set(self, entry_id: str, value: str) -> None: ...
    def delete(self, entry_id: str) -> None: ...


class KeyringVaultBackend:
    """Adapter for supported native OS credential stores; insecure backends are rejected."""

    _ALLOWED_BACKENDS = (
        "keyring.backends.SecretService",
        "keyring.backends.macOS",
        "keyring.backends.Windows",
    )

    def __init__(self) -> None:
        try:
            import keyring
        except ImportError as exc:
            raise RuntimeError(
                "secure vault requires the 'keyring' package; install zrouter[secure-vault]"
            ) from exc
        backend = keyring.get_keyring()
        module = type(backend).__module__
        priority = getattr(backend, "priority", 0)
        if priority <= 0 or not any(module.startswith(name) for name in self._ALLOWED_BACKENDS):
            raise RuntimeError(
                "no supported native OS credential store is available; "
                "configure SecretService, macOS Keychain, or Windows Credential Locker. "
                "Plaintext fallback is intentionally disabled."
            )
        self._keyring = keyring

    def get(self, entry_id: str) -> str | None:
        return self._keyring.get_password(KEYRING_SERVICE, entry_id)

    def set(self, entry_id: str, value: str) -> None:
        self._keyring.set_password(KEYRING_SERVICE, entry_id, value)

    def delete(self, entry_id: str) -> None:
        try:
            self._keyring.delete_password(KEYRING_SERVICE, entry_id)
        except self._keyring.errors.PasswordDeleteError:
            return


def _validate_entry_id(entry_id: str) -> str:
    if (
        not isinstance(entry_id, str)
        or not entry_id
        or len(entry_id) > 128
        or any(ord(char) < 32 for char in entry_id)
    ):
        raise ValueError("vault entry id must be 1-128 printable characters")
    return entry_id


class Vault:
    """Credential metadata on disk; credential values live only in the native OS keyring."""

    def __init__(
        self, path: Path = VAULT_FILE, backend: VaultBackend | None = None
    ) -> None:
        self.path = Path(path)
        self._backend = backend
        self._entries: dict[str, VaultEntry] = {}
        self._lock = threading.RLock()
        self._load()

    def _get_backend(self) -> VaultBackend:
        if self._backend is None:
            self._backend = KeyringVaultBackend()
        return self._backend

    def _load(self) -> None:
        if self.path.is_symlink():
            raise RuntimeError("refusing to read a symlinked vault index")
        if not self.path.exists():
            self._entries = {}
            return
        try:
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(self.path, flags)
            try:
                with os.fdopen(fd, "r", encoding="utf-8") as stream:
                    data = json.load(stream)
            except Exception:
                try:
                    os.close(fd)
                except OSError:
                    pass
                raise
            if not isinstance(data, list):
                raise TypeError("vault index root must be a JSON array")
            entries: dict[str, VaultEntry] = {}
            for raw in data:
                if not isinstance(raw, dict):
                    raise TypeError("vault index entries must be objects")
                value = raw.get("value", {})
                if value:
                    raise RuntimeError(
                        "legacy plaintext vault detected; use the explicit "
                        "Vault.migrate_legacy(..., confirm=True) migration"
                    )
                metadata = {**raw, "value": {}}
                entry = VaultEntry.from_dict(metadata)
                _validate_entry_id(entry.id)
                entries[entry.id] = entry
            self._entries = entries
        except RuntimeError:
            raise
        except (OSError, ValueError, KeyError, TypeError) as exc:
            log.exception("Vault index could not be loaded; refusing to overwrite it")
            raise RuntimeError(
                "vault index is unreadable or corrupt; refusing to start with an empty vault"
            ) from exc

    def _save_index(self) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name == "posix":
            os.chmod(self.path.parent, 0o700)
        tmp = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            payload = [
                {
                    "id": entry.id,
                    "name": entry.name,
                    "kind": entry.kind,
                    "value": {},
                    "created_at": entry.created_at,
                    "updated_at": entry.updated_at,
                }
                for entry in self._entries.values()
            ]
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
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
            backend = self._get_backend() if self._entries else self._backend
            result: list[VaultEntry] = []
            for entry in self._entries.values():
                value = backend.get(entry.id) if backend is not None else None
                if value is None:
                    raise RuntimeError(f"vault secret is missing for entry {entry.id!r}")
                result.append(VaultEntry.from_dict({**entry.to_dict(), "value": json.loads(value)}))
            return result

    def get(self, entry_id: str) -> VaultEntry | None:
        entry_id = _validate_entry_id(entry_id)
        with self._lock:
            entry = self._entries.get(entry_id)
            if entry is None:
                return None
            value = self._get_backend().get(entry_id)
            if value is None:
                raise RuntimeError(f"vault secret is missing for entry {entry_id!r}")
            return VaultEntry.from_dict({**entry.to_dict(), "value": json.loads(value)})

    def add(self, entry: VaultEntry) -> VaultEntry:
        _validate_entry_id(entry.id)
        encoded = json.dumps(entry.value, separators=(",", ":"), ensure_ascii=False)
        with self._lock:
            backend = self._get_backend()
            previous = backend.get(entry.id)
            old_entry = self._entries.get(entry.id)
            backend.set(entry.id, encoded)
            self._entries[entry.id] = VaultEntry.from_dict({**entry.to_dict(), "value": {}})
            try:
                self._save_index()
            except Exception:
                self._entries.pop(entry.id, None)
                if old_entry is not None:
                    self._entries[entry.id] = old_entry
                if previous is None:
                    backend.delete(entry.id)
                else:
                    backend.set(entry.id, previous)
                raise
            return entry

    def update(self, entry_id: str, value: dict[str, Any]) -> VaultEntry | None:
        entry_id = _validate_entry_id(entry_id)
        with self._lock:
            entry = self._entries.get(entry_id)
            if entry is None:
                return None
            backend = self._get_backend()
            previous = backend.get(entry_id)
            if previous is None:
                raise RuntimeError(f"vault secret is missing for entry {entry_id!r}")
            backend.set(entry_id, json.dumps(value, separators=(",", ":"), ensure_ascii=False))
            updated = VaultEntry.from_dict({**entry.to_dict(), "value": {}, "updated_at": time.time()})
            self._entries[entry_id] = updated
            try:
                self._save_index()
            except Exception:
                self._entries[entry_id] = entry
                backend.set(entry_id, previous)
                raise
            return VaultEntry.from_dict({**updated.to_dict(), "value": value})

    def delete(self, entry_id: str) -> bool:
        entry_id = _validate_entry_id(entry_id)
        with self._lock:
            entry = self._entries.get(entry_id)
            if entry is None:
                return False
            backend = self._get_backend()
            previous = backend.get(entry_id)
            if previous is None:
                raise RuntimeError(f"vault secret is missing for entry {entry_id!r}")
            backend.delete(entry_id)
            del self._entries[entry_id]
            try:
                self._save_index()
            except Exception:
                self._entries[entry_id] = entry
                backend.set(entry_id, previous)
                raise
            return True

    @classmethod
    def migrate_legacy(
        cls,
        path: Path = VAULT_FILE,
        backend: VaultBackend | None = None,
        *,
        confirm: bool = False,
    ) -> int:
        """Move a legacy plaintext JSON vault into the OS keyring after explicit confirmation."""
        if not confirm:
            raise PermissionError("legacy vault migration requires confirm=True")
        path = Path(path)
        if path.is_symlink():
            raise RuntimeError("refusing to migrate a symlinked legacy vault")
        try:
            with path.open("r", encoding="utf-8") as stream:
                raw_entries = json.load(stream)
            if not isinstance(raw_entries, list):
                raise TypeError("legacy vault root must be a JSON array")
            entries = [VaultEntry.from_dict(item) for item in raw_entries]
            for entry in entries:
                _validate_entry_id(entry.id)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise RuntimeError("legacy vault is unreadable or invalid") from exc
        store = backend or KeyringVaultBackend()
        written: list[str] = []
        try:
            for entry in entries:
                store.set(entry.id, json.dumps(entry.value, separators=(",", ":"), ensure_ascii=False))
                written.append(entry.id)
            metadata = object.__new__(cls)
            metadata.path = path
            metadata._backend = store
            metadata._entries = {
                entry.id: VaultEntry.from_dict({**entry.to_dict(), "value": {}})
                for entry in entries
            }
            metadata._lock = threading.RLock()
            metadata._save_index()
        except Exception:
            for entry_id in written:
                try:
                    store.delete(entry_id)
                except Exception:
                    log.exception("failed to roll back keyring migration entry %s", entry_id)
            raise
        return len(entries)


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
