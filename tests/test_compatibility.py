"""Tests for compatibility false-skip override."""

from __future__ import annotations

import unittest
from pathlib import Path

from wingman.compatibility import _llm_skip_contradicts_profile, _rule_based_compat
from wingman.hooks import _deterministic_hooks
from wingman.profile_cache import load_merged, profile_from_merged


_RICH_PROFILE = (
    Path(__file__).resolve().parent.parent
    / "debug"
    / "wingman_profile_20260902_141741"
    / "extract"
    / "merged.json"
)


class TestCompatibilityOverride(unittest.TestCase):
    def test_detects_false_skip(self):
        if not _RICH_PROFILE.is_file():
            self.skipTest("rich profile fixture missing")
        merged = load_merged(_RICH_PROFILE.parent)
        assert merged is not None
        profile = profile_from_merged(merged, frame_count=14)
        profile.hooks = _deterministic_hooks(profile)
        hooks_summary = [
            {"label": h.label, "detail": h.detail, "tier": h.tier}
            for h in profile.hooks
        ]
        self.assertTrue(
            _llm_skip_contradicts_profile(
                "skip",
                ["profile effort is low", "no usable conversation hook"],
                profile,
                hooks_summary,
            )
        )

    def test_rule_based_likes_rich_profile(self):
        if not _RICH_PROFILE.is_file():
            self.skipTest("rich profile fixture missing")
        merged = load_merged(_RICH_PROFILE.parent)
        assert merged is not None
        profile = profile_from_merged(merged, frame_count=14)
        profile.hooks = _deterministic_hooks(profile)
        hooks_summary = [
            {"label": h.label, "detail": h.detail, "tier": h.tier}
            for h in profile.hooks
        ]
        result = _rule_based_compat(profile, hooks_summary, [18, 24], usage={})
        self.assertEqual(result.decision, "like")
        self.assertGreaterEqual(result.confidence_score, 6)


if __name__ == "__main__":
    unittest.main()
