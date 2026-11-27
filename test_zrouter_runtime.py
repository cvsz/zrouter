from __future__ import annotations

import unittest

import zrouter
import zrouter_runtime


class TestRuntimeCompatibility(unittest.TestCase):
    def test_legacy_module_reexports_runtime_primitives(self):
        for name in ("RateLimiter", "Stats", "TTLCache", "mask"):
            with self.subTest(name=name):
                self.assertIs(getattr(zrouter, name), getattr(zrouter_runtime, name))


if __name__ == "__main__":
    unittest.main()
