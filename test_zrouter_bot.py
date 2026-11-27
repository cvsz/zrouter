from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path

from zrouter_bot import Vault, VaultEntry


class TestVaultStorage(unittest.TestCase):
    def test_round_trip_and_private_file_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "vault.json"
            vault = Vault(path)
            entry = VaultEntry(
                id="entry-1",
                name="test login",
                kind="login",
                value={"username": "sea", "password": "test-secret"},
            )
            vault.add(entry)

            loaded = Vault(path)
            self.assertEqual(loaded.get("entry-1").value, entry.value)
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)

    def test_corrupt_vault_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "vault.json"
            path.write_text("{invalid", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                Vault(path)

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
                Vault(link)


if __name__ == "__main__":
    unittest.main()
