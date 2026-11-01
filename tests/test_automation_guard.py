"""Tests for automation policy vs human/dry-run judgment."""

from __future__ import annotations

import unittest

import config
from wingman.automation_guard import apply_active_now_policy, would_defer_for_active_now
from wingman.models import CompatibilityResult, ConversationHook, ProfileAnalysis


class TestAutomationGuard(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_run = config.RUN_MODE
        self._orig_dry = config.DRY_RUN
        self._orig_approval = config.HUMAN_APPROVAL
        self._orig_auto = config.AUTO_ACTION

    def tearDown(self) -> None:
        config.RUN_MODE = self._orig_run
        config.DRY_RUN = self._orig_dry
        config.HUMAN_APPROVAL = self._orig_approval
        config.AUTO_ACTION = self._orig_auto

    def _inactive_like_profile(self) -> ProfileAnalysis:
        return ProfileAnalysis(
            name="a",
            age=19,
            location="Example city",
            hooks=[
                ConversationHook(
                    label="My most irrational fear is",
                    detail="you being stoic",
                    tier=1,
                    source="prompt",
                )
            ],
        )

    def test_dry_run_does_not_defer_inactive_like(self) -> None:
        config.RUN_MODE = "automated"
        config.DRY_RUN = True
        profile = self._inactive_like_profile()
        result = CompatibilityResult(
            decision="like",
            confidence_score=7,
            why=["Rich prompts"],
        )
        out = apply_active_now_policy(profile, result)
        self.assertEqual(out.decision, "like")
        self.assertFalse(any("automation policy" in w.lower() for w in out.why))

    def test_assisted_mode_does_not_defer_inactive_like(self) -> None:
        config.RUN_MODE = "assisted"
        config.DRY_RUN = False
        config.HUMAN_APPROVAL = True
        config.AUTO_ACTION = True
        profile = self._inactive_like_profile()
        result = CompatibilityResult(
            decision="like",
            confidence_score=7,
            why=["Rich prompts"],
        )
        out = apply_active_now_policy(profile, result)
        self.assertEqual(out.decision, "like")

    def test_live_automation_defers_inactive_like(self) -> None:
        config.RUN_MODE = "automated"
        config.DRY_RUN = False
        config.HUMAN_APPROVAL = False
        profile = self._inactive_like_profile()
        result = CompatibilityResult(
            decision="like",
            confidence_score=7,
            why=["Rich prompts"],
        )
        self.assertTrue(would_defer_for_active_now(profile, result))
        out = apply_active_now_policy(profile, result)
        self.assertEqual(out.decision, "skip")

    def test_human_mode_never_defers(self) -> None:
        config.RUN_MODE = "dry_run"
        config.DRY_RUN = True
        profile = self._inactive_like_profile()
        result = CompatibilityResult(decision="like", confidence_score=7, why=[])
        out = apply_active_now_policy(profile, result)
        self.assertEqual(out.decision, "like")


if __name__ == "__main__":
    unittest.main()
