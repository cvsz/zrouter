from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from zrouter_bot import Vault, VaultEntry
from zrouter_bot_storage import KeyringVaultBackend


class InMemoryKeyring:
    def __init__(self):
        self.values = {}

    def get(self, entry_id):
        return self.values.get(entry_id)

    def set(self, entry_id, value):
        self.values[entry_id] = value

    def delete(self, entry_id):
        self.values.pop(entry_id, None)


class TestVaultStorage(unittest.TestCase):
    def test_round_trip_keeps_secret_out_of_index(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "vault.json"
            backend = InMemoryKeyring()
            vault = Vault(path, backend=backend)
            entry = VaultEntry(
                id="entry-1",
                name="test login",
                kind="login",
                value={"username": "tester", "password": "synthetic-test-secret"},
            )
            vault.add(entry)

            loaded = Vault(path, backend=backend)
            self.assertEqual(loaded.get("entry-1").value, entry.value)
            self.assertNotIn("synthetic-test-secret", path.read_text(encoding="utf-8"))
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)

    def test_legacy_plaintext_requires_explicit_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "vault.json"
            entry = VaultEntry(
                id="legacy-1",
                name="legacy",
                kind="login",
                value={"password": "old-secret"},
            )
            path.write_text(json.dumps([entry.to_dict()]), encoding="utf-8")
            legacy_vault = Vault(path, backend=InMemoryKeyring())
            with self.assertRaisesRegex(RuntimeError, "legacy plaintext vault"):
                legacy_vault.list()
            with self.assertRaises(PermissionError):
                Vault.migrate_legacy(path, backend=InMemoryKeyring())

    def test_explicit_migration_moves_secrets_to_backend(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "vault.json"
            entry = VaultEntry(
                id="legacy-2",
                name="legacy",
                kind="login",
                value={"password": "old-secret"},
            )
            path.write_text(json.dumps([entry.to_dict()]), encoding="utf-8")
            backend = InMemoryKeyring()
            self.assertEqual(Vault.migrate_legacy(path, backend, confirm=True), 1)
            restored = Vault(path, backend=backend)
            self.assertEqual(restored.get("legacy-2").value, {"password": "old-secret"})
            self.assertNotIn("old-secret", path.read_text(encoding="utf-8"))

    def test_insecure_keyring_backend_is_rejected(self):
        class InsecureBackend:
            __module__ = "keyrings.alt.file"
            priority = 1

        fake_keyring = SimpleNamespace(
            get_keyring=lambda: InsecureBackend(),
            errors=SimpleNamespace(PasswordDeleteError=Exception),
        )
        with (
            mock.patch.dict(sys.modules, {"keyring": fake_keyring}),
            self.assertRaisesRegex(
                RuntimeError, "Plaintext fallback is intentionally disabled"
            ),
        ):
            KeyringVaultBackend()

    def test_missing_keyring_secret_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "vault.json"
            path.write_text(
                json.dumps(
                    [
                        {
                            "id": "missing-1",
                            "name": "missing",
                            "kind": "secret",
                            "value": {},
                            "created_at": 1.0,
                            "updated_at": 1.0,
                        }
                    ]
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "secret is missing"):
                Vault(path, backend=InMemoryKeyring()).get("missing-1")


    def test_invalid_keyring_payload_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "vault.json"
            path.write_text(
                json.dumps(
                    [
                        {
                            "id": "bad-1",
                            "name": "bad",
                            "kind": "secret",
                            "value": {},
                            "created_at": 1.0,
                            "updated_at": 1.0,
                        }
                    ]
                ),
                encoding="utf-8",
            )
            backend = InMemoryKeyring()
            backend.set("bad-1", "[]")
            with self.assertRaisesRegex(TypeError, "must be a JSON object"):
                Vault(path, backend=backend).list()

    def test_corrupt_vault_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "vault.json"
            path.write_text("{invalid", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                Vault(path, backend=InMemoryKeyring())

    def test_symlinked_vault_is_rejected(self):
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks are unavailable")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target.json"
            target.write_text("[]", encoding="utf-8")
            link = root / "vault.json"
            try:
                link.symlink_to(target)
            except OSError as exc:
                self.skipTest(f"symlink creation is unavailable: {exc}")
            with self.assertRaises(RuntimeError):
                Vault(link, backend=InMemoryKeyring())


if __name__ == "__main__":
    unittest.main()
