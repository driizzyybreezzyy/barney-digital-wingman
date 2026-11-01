"""Platform registry tests."""

from __future__ import annotations

import unittest

from wingman.platforms import normalize_platform


class TestPlatforms(unittest.TestCase):
    def test_supported_platforms_normalize(self) -> None:
        self.assertEqual(normalize_platform(" Bumble "), "bumble")
        self.assertEqual(normalize_platform(None), "generic")

    def test_unknown_platform_is_explicitly_rejected(self) -> None:
        with self.assertRaises(ValueError):
            normalize_platform("unknown-app")


if __name__ == "__main__":
    unittest.main()
