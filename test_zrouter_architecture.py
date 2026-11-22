from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import zrouter
import zrouter_application
import zrouter_catalog
import zrouter_cli
import zrouter_config
from zrouter_config import read_secret_file


class TestArchitectureCompatibility(unittest.TestCase):
    def test_application_facade_identity(self) -> None:
        self.assertIs(zrouter.FreeRouter, zrouter_application.FreeRouter)
        self.assertIs(zrouter.classify, zrouter_application.classify)

    def test_configuration_facade_identity(self) -> None:
        self.assertIs(zrouter.CFG, zrouter_config.CFG)
        self.assertIs(zrouter.Settings, zrouter_config.Settings)
        self.assertIs(zrouter.ProviderConfig, zrouter_config.ProviderConfig)
        self.assertIs(zrouter.Key, zrouter_config.Key)

    def test_catalog_facade_identity(self) -> None:
        self.assertIs(zrouter.CATALOG, zrouter_catalog.CATALOG)
        self.assertIs(zrouter.ModelsCatalog, zrouter_catalog.ModelsCatalog)

    def test_cli_facade_identity(self) -> None:
        self.assertIs(zrouter.main, zrouter_cli.main)
        self.assertIs(zrouter.build_parser, zrouter_cli.build_parser)

    def test_secret_file_reader_is_bounded_and_rejects_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            secret_path = Path(directory) / "router-token"
            secret_path.write_text("synthetic-token\\n", encoding="utf-8")
            self.assertEqual(read_secret_file(str(secret_path)), "synthetic-token")
            with self.assertRaisesRegex(ValueError, "size limit"):
                read_secret_file(str(secret_path), max_bytes=4)
            if hasattr(Path, "symlink_to"):
                link_path = Path(directory) / "router-token-link"
                link_path.symlink_to(secret_path)
                with self.assertRaisesRegex(ValueError, "symlinked"):
                    read_secret_file(str(link_path))

    def test_cli_parser_preserves_existing_commands(self) -> None:
        parser = zrouter.build_parser()
        self.assertEqual(parser.parse_args(["chat", "hello"]).cmd, "chat")
        self.assertEqual(parser.parse_args(["serve", "--port", "8123"]).port, 8123)
        self.assertEqual(parser.parse_args(["bot", "status"]).subcmd, "status")


if __name__ == "__main__":
    unittest.main()
