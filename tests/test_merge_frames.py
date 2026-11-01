"""Unit tests for deterministic frame merge (no Ollama)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from wingman.merge_frames import merge_partials
from wingman.profile_analyzer import merge_cached_partials, _build_analysis
from wingman.profile_cache import load_merged

_FIXTURE_DIR = (
    Path(__file__).resolve().parent.parent
    / "debug"
    / "wingman_profile_20260902_020011"
    / "extract"
)


class TestDeterministicMerge(unittest.TestCase):
    def test_merge_vishakha_partials(self):
        if not _FIXTURE_DIR.is_dir():
            self.skipTest("Vishakha fixture extract dir not present")

        partials: list[tuple[int, dict]] = []
        for path in sorted(_FIXTURE_DIR.glob("frame_*.json")):
            idx = int(path.stem.split("_")[1])
            partials.append((idx, json.loads(path.read_text(encoding="utf-8"))))

        merged = merge_partials(partials, frame_count=len(partials))

        self.assertEqual(merged["name"], "vishakha")
        self.assertEqual(merged["age"], 21)
        self.assertIn("rajasthan", merged["location"].lower())
        self.assertEqual(merged["merge_method"], "deterministic_python")
        self.assertEqual(len(merged["source_frames"]), 9)
        self.assertGreater(len(merged["prompts"]), 0)
        self.assertGreater(len(merged["photo_contexts"]), 0)
        self.assertGreater(len(merged["evidence_bullets"]), 0)
        self.assertIn("source_frames", merged["prompts"][0])

        # Real Hinge prompt preserved
        prompt_texts = [p["prompt_text"] for p in merged["prompts"]]
        self.assertTrue(
            any("dating goals" in t for t in prompt_texts),
            msg=f"prompts: {prompt_texts}",
        )

    def test_dedupes_exact_photo_descriptions_only(self):
        partials = [
            (0, {
                "photo_contexts": [{"index": 1, "description": "Person in a car"}],
                "prompts": [],
                "interest_signals": [],
                "evidence_bullets": [],
            }),
            (1, {
                "photo_contexts": [{"index": 1, "description": "person in a car"}],
                "prompts": [],
                "interest_signals": [],
                "evidence_bullets": [],
            }),
            (2, {
                "photo_contexts": [{"index": 1, "description": "Person at a cafe"}],
                "prompts": [],
                "interest_signals": [],
                "evidence_bullets": [],
            }),
        ]
        merged = merge_partials(partials, frame_count=3)
        self.assertEqual(len(merged["photo_contexts"]), 2)

    def test_malformed_partial_does_not_block_merge(self):
        partials = [
            (0, {"name": "test", "prompts": [], "photo_contexts": [], "interest_signals": [], "evidence_bullets": []}),
            (2, {"name": "test", "prompts": [{"prompt_text": "A prompt", "answer": "An answer", "readable": True}], "photo_contexts": [], "interest_signals": [], "evidence_bullets": []}),
        ]
        merged = merge_partials(partials, frame_count=3)
        self.assertEqual(merged["name"], "test")
        self.assertEqual(len(merged["prompts"]), 1)

    def test_merge_cached_writes_merged_json(self):
        if not _FIXTURE_DIR.is_dir():
            self.skipTest("Vishakha fixture extract dir not present")

        import tempfile
        import shutil

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "extract"
            shutil.copytree(_FIXTURE_DIR, dest)
            merged_path = dest / "merged.json"
            if merged_path.exists():
                merged_path.unlink()

            merged = merge_cached_partials(dest, expected_frames=9)
            self.assertTrue(merged_path.is_file())
            on_disk = load_merged(dest)
            self.assertIsNotNone(on_disk)
            assert on_disk is not None
            self.assertEqual(on_disk["name"], merged["name"])

            analysis = _build_analysis(merged)
            self.assertEqual(analysis.name, "vishakha")
            self.assertEqual(analysis.age, 21)


if __name__ == "__main__":
    unittest.main()
