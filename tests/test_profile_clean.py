"""Tests for profile cleaning and deterministic hooks."""

from __future__ import annotations

import unittest
from pathlib import Path

from wingman.hooks import _deterministic_hooks
from wingman.models import ProfileAnalysis, PromptItem
from wingman.profile_cache import profile_from_merged, load_merged
from wingman.profile_clean import (
    clean_extracted_name,
    clean_prompts,
    is_meta_prompt,
    normalize_prompt_item,
    split_merged_hinge_prompt,
)


_VISHAKHA = (
    Path(__file__).resolve().parent.parent
    / "debug"
    / "wingman_profile_20260902_020011"
    / "extract"
    / "merged.json"
)
_V_PROFILE = (
    Path(__file__).resolve().parent.parent
    / "debug"
    / "wingman_profile_20260902_125021"
    / "extract"
    / "merged.json"
)
_TULSIBAG = (
    Path(__file__).resolve().parent.parent
    / "debug"
    / "wingman_profile_20260902_133907"
    / "extract"
    / "merged.json"
)
_RICH_PROFILE = (
    Path(__file__).resolve().parent.parent
    / "debug"
    / "wingman_profile_20260902_141741"
    / "extract"
    / "merged.json"
)


class TestProfileClean(unittest.TestCase):
    def test_filters_meta_prompts(self):
        self.assertTrue(is_meta_prompt("what is the name of the person in the photo?", "vishakha"))
        self.assertTrue(is_meta_prompt("vishakha", "vishakha"))
        self.assertTrue(is_meta_prompt("What is the person wearing?", "The person is wearing a black top."))
        self.assertTrue(is_meta_prompt("What is the person's name?", "Not visible"))
        self.assertTrue(is_meta_prompt("v shows thoughtful signals", "v shows thoughtful signals"))
        self.assertFalse(is_meta_prompt("Don't hate me if I", "Laugh at the most serious situations"))

    def test_split_merged_hinge_prompt(self):
        q, a = split_merged_hinge_prompt(
            "The way to win me over is being spontaneous asf",
            "The way to win me over is being spontaneous asf",
        )
        self.assertEqual(q, "The way to win me over is")
        self.assertEqual(a, "being spontaneous asf")

    def test_keeps_self_contained_prompt(self):
        text = "that's my go to face and go to top"
        q, a = split_merged_hinge_prompt(text, text)
        self.assertEqual(q, text)
        self.assertFalse(is_meta_prompt(q, a))

    def test_vishakha_clean_prompts(self):
        if not _VISHAKHA.is_file():
            self.skipTest("merged.json fixture missing")
        merged = load_merged(_VISHAKHA.parent)
        assert merged is not None
        profile = profile_from_merged(merged, frame_count=9)
        cleaned = clean_prompts(profile)
        texts = [p.prompt_text for p in cleaned]
        self.assertTrue(any("Don't hate me if I" in t for t in texts))
        self.assertTrue(any("Yapping" in p.answer for p in cleaned))
        self.assertFalse(any("what is the name of the person" in t.lower() for t in texts))

    def test_v_profile_clean_prompts(self):
        if not _V_PROFILE.is_file():
            self.skipTest("v merged.json fixture missing")
        merged = load_merged(_V_PROFILE.parent)
        assert merged is not None
        profile = profile_from_merged(merged, frame_count=14)
        cleaned = clean_prompts(profile)
        answers = [p.answer for p in cleaned]
        prompts = [p.prompt_text for p in cleaned]

        self.assertFalse(any("thoughtful signals" in a for a in answers))
        self.assertFalse(any("not visible" in a.lower() for a in answers))
        self.assertFalse(any("the person is wearing" in a.lower() for a in answers))
        self.assertIn("bacchon ka hone wala baap", answers)
        self.assertIn("being spontaneous asf", answers)
        self.assertIn("good perfumes", answers)
        self.assertEqual(cleaned[0].answer, "bacchon ka hone wala baap")

    def test_v_profile_hooks_rank_life_partner_first(self):
        if not _V_PROFILE.is_file():
            self.skipTest("v merged.json fixture missing")
        merged = load_merged(_V_PROFILE.parent)
        assert merged is not None
        profile = profile_from_merged(merged, frame_count=14)
        hooks = _deterministic_hooks(profile)
        self.assertGreaterEqual(len(hooks), 3)
        self.assertIn("bacchon", hooks[0].detail.lower())

    def test_filters_hinge_ui_and_fabricated(self):
        self.assertTrue(is_meta_prompt("Keep going!", "We're learning who you like."))
        self.assertTrue(is_meta_prompt("Learning your type", "One like goes a long way"))
        self.assertTrue(is_meta_prompt("Life partner", "The way to win me over is"))
        self.assertTrue(
            is_meta_prompt(
                "Life partner",
                "I'm looking for a partner who can keep up with my busy schedule and share my interests in technology and travel.",
            )
        )
        self.assertEqual(clean_extracted_name("lowercase first name or empty"), "unknown")

    def test_split_irrational_fear_without_is(self):
        from wingman.profile_clean import repair_prompt_answer

        q, a = repair_prompt_answer("My most irrational fear you being stoic", "")
        self.assertEqual(q, "My most irrational fear is")
        self.assertEqual(a, "you being stoic")

    def test_stoic_prompt_ranks_high(self):
        from wingman.profile_clean import prompt_quality_score

        item = PromptItem("My most irrational fear is", "you being stoic")
        self.assertLessEqual(prompt_quality_score(item), 2)

    def test_tulsibag_clean_prompts(self):
        if not _TULSIBAG.is_file():
            self.skipTest("tulsibag merged.json missing")
        merged = load_merged(_TULSIBAG.parent)
        assert merged is not None
        profile = profile_from_merged(merged, frame_count=9)
        self.assertEqual(profile.name, "unknown")
        cleaned = clean_prompts(profile)
        answers = [p.answer for p in cleaned]
        self.assertIn("think about the Pythagorean theorem", answers)
        self.assertIn("building a recreational facility for all the homies", answers)
        self.assertIn("Bob, Kevin and Stuart", answers)
        self.assertFalse(any("learning who you like" in a.lower() for a in answers))
        self.assertFalse(any("the way to win me over" in a.lower() for a in answers))

    def test_tulsibag_hooks(self):
        if not _TULSIBAG.is_file():
            self.skipTest("tulsibag merged.json missing")
        merged = load_merged(_TULSIBAG.parent)
        assert merged is not None
        profile = profile_from_merged(merged, frame_count=9)
        hooks = _deterministic_hooks(profile)
        self.assertGreaterEqual(len(hooks), 3)
        self.assertTrue(all(h.source == "prompt" for h in hooks[:3]))
        self.assertIn("pythagorean", hooks[0].detail.lower())

    def test_rich_profile_clean_prompts(self):
        if not _RICH_PROFILE.is_file():
            self.skipTest("rich profile fixture missing")
        merged = load_merged(_RICH_PROFILE.parent)
        assert merged is not None
        profile = profile_from_merged(merged, frame_count=14)
        self.assertEqual(profile.name, "unknown")
        cleaned = clean_prompts(profile)
        answers = [p.answer.lower() for p in cleaned]
        self.assertTrue(any("greek philosophers" in a for a in answers))
        self.assertTrue(any("yap about your niche" in a for a in answers))
        self.assertTrue(any("pun relay" in a for a in answers))
        self.assertFalse(any("busy schedule" in a for a in answers))
        self.assertFalse(any("learning who you like" in a for a in answers))

    def test_dedupe_hooks_by_answer(self):
        from wingman.hooks import _dedupe_hooks
        from wingman.models import ConversationHook

        hooks = _dedupe_hooks([
            ConversationHook("My most irrational fear you being stoic", "you being stoic", 1, "prompt"),
            ConversationHook("My most irrational fear", "you being stoic", 1, "prompt"),
            ConversationHook("I geek out on", "the nbhd", 1, "prompt"),
        ])
        details = [h.detail for h in hooks]
        self.assertEqual(len(hooks), 2)
        self.assertEqual(details.count("you being stoic"), 1)

    def test_normalize_splits_perfumes(self):
        item = normalize_prompt_item(
            PromptItem(
                "The key to my heart is good perfumes",
                "The key to my heart is good perfumes",
            )
        )
        self.assertEqual(item.prompt_text, "The key to my heart is")
        self.assertEqual(item.answer, "good perfumes")


if __name__ == "__main__":
    unittest.main()
