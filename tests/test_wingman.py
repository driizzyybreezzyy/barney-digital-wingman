"""Unit tests for Digital Wingman Phase 2 (no Ollama required)."""

from __future__ import annotations

import unittest

import config
from wingman.approval import hinge_actions_allowed
from wingman.opener import validate_opener, HookContext
from wingman.personality import load_aryan_profile


class TestOpenerValidation(unittest.TestCase):
    def _hook(self, detail: str) -> HookContext:
        words = tuple(w for w in detail.lower().split() if len(w) > 3)
        return HookContext(
            label="prompt",
            detail=detail,
            evidence=detail,
            priority=1,
            anchor_words=words or (detail.lower(),),
        )

    def test_rejects_generic_compliment(self):
        hook = self._hook("favourite line from a film")
        valid, reason = validate_opener(
            "Hey, your photo looks amazing!",
            hook,
        )
        self.assertFalse(valid)
        self.assertTrue("Hey" in reason or "generic" in reason.lower() or "appearance" in reason.lower())

    def test_rejects_how_are_you(self):
        hook = self._hook("film prompt answer ddlj")
        valid, _ = validate_opener("How are you?", hook)
        self.assertFalse(valid)

    def test_accepts_hook_specific(self):
        hook = self._hook("favourite line from a film")
        valid, reason = validate_opener(
            "ok but what's the film line — need to judge your taste",
            hook,
        )
        self.assertTrue(valid, reason)


class TestSafety(unittest.TestCase):
    def test_dry_run_disallows_hinge_actions(self):
        self.assertEqual(config.RUN_MODE, "dry_run")
        self.assertTrue(config.HUMAN_APPROVAL)
        self.assertFalse(config.AUTO_ACTION)
        self.assertFalse(hinge_actions_allowed())


class TestPersonality(unittest.TestCase):
    def test_user_profile_loads(self):
        profile = load_aryan_profile()
        self.assertIn("identity", profile)
        self.assertIn("personality", profile)
        self.assertIn("traits", profile["personality"])


if __name__ == "__main__":
    unittest.main()
