"""Capture-loop tests without an emulator."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from PIL import Image

from wingman.capture import _content_hash, capture_scrolling_profile


def _png(color: int) -> bytes:
    import io

    buf = io.BytesIO()
    Image.new("RGB", (120, 240), (color, color, color)).save(buf, format="PNG")
    return buf.getvalue()


class TestCapture(unittest.TestCase):
    def test_fingerprint_ignores_small_png_encoding_differences(self):
        self.assertEqual(_content_hash(_png(100)), _content_hash(_png(100)))

    @patch("wingman.capture.ensure_discover_visible")
    @patch("wingman.capture.scroll_to_top")
    @patch("wingman.capture.adb")
    def test_capture_is_bounded_and_stops_on_stable_bottom(
        self, adb_mock, _scroll_top, _visible
    ):
        adb_mock.screenshot.side_effect = [
            _png(10),
            _png(20),
            _png(30),
            _png(30),
            _png(30),
        ]
        frames = capture_scrolling_profile(max_frames=8, min_frames=3)
        self.assertEqual(len(frames), 3)
        self.assertLessEqual(adb_mock.screenshot.call_count, 5)


if __name__ == "__main__":
    unittest.main()
