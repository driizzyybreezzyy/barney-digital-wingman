"""Tests for opener validation and hook ranking."""

from __future__ import annotations

import unittest

from wingman.models import PromptItem, ProfileAnalysis
from wingman.opener import HookContext, rank_hooks_for_openers, validate_opener


class TestOpenerValidation(unittest.TestCase):
    def _hook(self, detail: str, **kwargs) -> HookContext:
        return HookContext(
            label=kwargs.get("label", "prompt"),
            detail=detail,
            evidence=kwargs.get("evidence", detail),
            priority=1,
            anchor_words=kwargs.get("anchor_words", (detail.split()[0].lower(),)),
        )

    def test_rejects_hey(self):
        hook = self._hook("Yapping", anchor_words=("yapping", "yap"))
        valid, reason = validate_opener(
            "Hey, yapping as a skill is unhinged and i need proof you're elite at it",
            hook,
        )
        self.assertFalse(valid)
        self.assertIn("Hey", reason)

    def test_rejects_appearance_hair(self):
        hook = self._hook("liberal", anchor_words=("liberal",))
        valid, _ = validate_opener(
            "I noticed you have long wavy hair, very unique liberal vibes",
            hook,
        )
        self.assertFalse(valid)

    def test_rejects_interview_question(self):
        hook = self._hook("Yapping", anchor_words=("yapping", "yap"))
        valid, reason = validate_opener(
            "What's the funniest thing you've ever yapped about?",
            hook,
        )
        self.assertFalse(valid)
        self.assertIn("interview", reason.lower())

    def test_rejects_verbatim_quote(self):
        hook = HookContext(
            label="Don't hate me if I",
            detail="Laugh at the most serious situations",
            evidence="prompt",
            priority=2,
            anchor_words=("laugh", "serious", "situations"),
            hook_key="serious",
        )
        valid, reason = validate_opener(
            "Don't hate me if I laugh at the most serious situations.",
            hook,
        )
        self.assertFalse(valid)
        self.assertIn("verbatim", reason.lower())

    def test_accepts_yapping_tease(self):
        hook = self._hook(
            "Yapping",
            label="unusual skill",
            anchor_words=("yapping", "yap", "skill", "bold"),
        )
        valid, reason = validate_opener(
            "yapping listed as a skill is bold. i need proof you're actually elite at it",
            hook,
        )
        self.assertTrue(valid, reason)

    def test_rejects_unhinged_respect_template(self):
        hook = self._hook(
            "a bud magnum",
            label="The way to win me over is",
            anchor_words=("magnum", "bud"),
            hook_key="bud_magnum",
        )
        valid, reason = validate_opener(
            "a bud magnum is unhinged. respect.",
            hook,
        )
        self.assertFalse(valid)
        self.assertIn("generic", reason.lower())

    def test_rank_vishakha_hooks(self):
        profile = ProfileAnalysis(
            prompts=[
                PromptItem("figuring out my dating goals", "liberal"),
                PromptItem("Don't hate me if I", "Laugh at the most serious situations"),
                PromptItem("unusual skill", "Yapping"),
            ]
        )
        hooks = rank_hooks_for_openers(profile)
        self.assertGreaterEqual(len(hooks), 2)
        self.assertEqual(hooks[0].detail, "Yapping")

    def test_rank_v_profile_hooks(self):
        profile = ProfileAnalysis(
            prompts=[
                PromptItem("v shows thoughtful signals", "v shows thoughtful signals"),
                PromptItem("Life partner", "bacchon ka hone wala baap"),
                PromptItem(
                    "The way to win me over is being spontaneous asf",
                    "The way to win me over is being spontaneous asf",
                ),
            ]
        )
        hooks = rank_hooks_for_openers(profile)
        self.assertEqual(hooks[0].detail, "bacchon ka hone wala baap")

    def test_rejects_prompt_title_without_answer(self):
        hook = HookContext(
            label="An award my family would give me",
            detail="Coming up with best arguments",
            evidence="prompt",
            priority=1,
            anchor_words=("arguments", "family", "award"),
            hook_key="family_arguments",
        )
        valid, reason = validate_opener(
            "An award my family would give me is either a joke or a challenge.",
            hook,
        )
        self.assertFalse(valid)
        self.assertIn("prompt title", reason.lower())

    def test_accepts_family_arguments_tease(self):
        hook = HookContext(
            label="An award my family would give me",
            detail="Coming up with best arguments",
            evidence="prompt",
            priority=1,
            anchor_words=("arguments", "family", "award", "elite", "chaos"),
            hook_key="family_arguments",
        )
        valid, reason = validate_opener(
            "coming up with best arguments as a family award is either elite or chaos. defend it.",
            hook,
        )
        self.assertTrue(valid, reason)

    def test_accepts_life_partner_tease(self):
        hook = HookContext(
            label="Life partner",
            detail="bacchon ka hone wala baap",
            evidence="prompt",
            priority=1,
            anchor_words=("bacchon", "baap", "life", "partner"),
            hook_key="life_partner",
        )
        valid, reason = validate_opener(
            "bacchon ka hone wala baap as a life partner answer is the boldest dad joke on hinge i've seen",
            hook,
        )
        self.assertTrue(valid, reason)


if __name__ == "__main__":
    unittest.main()
