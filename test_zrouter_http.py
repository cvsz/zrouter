from __future__ import annotations

import unittest

import zrouter
import zrouter_contracts
import zrouter_http


class TestHttpCompatibility(unittest.TestCase):
    def test_router_error_reexport_identity(self):
        self.assertIs(zrouter.RouterError, zrouter_contracts.RouterError)

    def test_request_size_contract(self):
        self.assertEqual(zrouter.MAX_REQUEST_BYTES, zrouter_contracts.MAX_REQUEST_BYTES)
        self.assertEqual(zrouter.MAX_REQUEST_BYTES, 16 * 1024 * 1024)

    def test_http_adapter_exposes_expected_operations(self):
        self.assertTrue(callable(zrouter._read_body))
        self.assertTrue(callable(zrouter.make_handler))
        self.assertTrue(callable(zrouter.serve))
        self.assertTrue(callable(zrouter_http.make_handler))
        self.assertTrue(callable(zrouter_http.serve))


if __name__ == "__main__":
    unittest.main()
