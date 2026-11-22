from __future__ import annotations

import tempfile
import uuid
import unittest
from pathlib import Path

from zrouter_bot import Vault, VaultEntry
from zrouter_bot_storage import KEYRING_SERVICE, KeyringVaultBackend


class TestNativeKeyringIntegration(unittest.TestCase):
    def test_native_os_credential_store_round_trip(self) -> None:
        backend = KeyringVaultBackend()
        entry_id = f"ci-{uuid.uuid4()}"
        secret_value = {"token": f"synthetic-{uuid.uuid4()}"}
        with tempfile.TemporaryDirectory(prefix="zrouter-keyring-") as directory:
            vault_path = Path(directory) / "vault.json"
            vault = Vault(vault_path, backend=backend)
            try:
                created = VaultEntry(
                    id=entry_id,
                    name="native keyring integration",
                    kind="test",
                    value=secret_value,
                )
                vault.add(created)
                restored = vault.get(entry_id)
                self.assertIsNotNone(restored)
                self.assertEqual(restored.value, secret_value)
                self.assertNotIn(secret_value["token"], vault_path.read_text(encoding="utf-8"))
                self.assertTrue(KEYRING_SERVICE)
            finally:
                vault.delete(entry_id)


if __name__ == "__main__":
    unittest.main()
