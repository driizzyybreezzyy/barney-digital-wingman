"""Tests for compatibility why sanitization."""

from __future__ import annotations

import unittest

from wingman.compatibility import sanitize_compat_why
from wingman.models import ProfileAnalysis, PromptItem


class TestCompatSanitize(unittest.TestCase):
    def test_drops_mountain_hallucination(self) -> None:
        profile = ProfileAnalysis(
            name="a",
            age=19,
            prompts=[
                PromptItem("My most irrational fear is", "you being stoic"),
                PromptItem("My simple pleasures", "the nbhd"),
            ],
        )
        why = [
            "Strong stoic hook on irrational fear prompt",
            "Mountainous landscape hook is compelling",
        ]
        cleaned = sanitize_compat_why(profile, why)
        self.assertIn(why[0], cleaned)
        self.assertNotIn(why[1], cleaned)


if __name__ == "__main__":
    unittest.main()
