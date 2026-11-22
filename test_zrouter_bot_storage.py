from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import zrouter_bot
import zrouter_bot_storage


class TestBotStorageCompatibility(unittest.TestCase):
    def test_legacy_module_reexports_storage_classes(self):
        self.assertIs(zrouter_bot.Vault, zrouter_bot_storage.Vault)
        self.assertIs(zrouter_bot.Memory, zrouter_bot_storage.Memory)

    def test_vault_storage_class_keeps_secure_backend_contract(self):
        self.assertTrue(hasattr(zrouter_bot_storage, "KeyringVaultBackend"))
        self.assertTrue(hasattr(zrouter_bot_storage, "VaultBackend"))

    def test_memory_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            store = zrouter_bot_storage.Memory(Path(directory) / "memory.json")
            store.set("theme", {"mode": "dark"})
            restored = zrouter_bot_storage.Memory(store.path)
            self.assertEqual(restored.get("theme"), {"mode": "dark"})
            self.assertTrue(restored.delete("theme"))
            self.assertFalse(restored.delete("theme"))


if __name__ == "__main__":
    unittest.main()
