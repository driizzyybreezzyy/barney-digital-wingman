#!/usr/bin/env python3
"""Offline resume validation for a cached profile run (no live capture)."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

import config
from wingman.approval import hinge_actions_allowed, print_recommendation
from wingman.opener import _validate_opener
from wingman.pipeline import run_pipeline
from wingman.self_profile import load_cached_self_profile, self_profile_summary


def _load_frames(frames_dir: Path) -> list[bytes]:
    files = sorted(frames_dir.glob("frame_*.png"))
    if not files:
        raise FileNotFoundError(f"No frame_*.png in {frames_dir}")
    return [f.read_bytes() for f in files]


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Validate cached profile resume")
    parser.add_argument(
        "--frames-dir",
        type=Path,
        default=Path("debug/wingman_profile_20260902_020011"),
    )
    parser.add_argument(
        "--force-downstream",
        action="store_true",
        help="Ignore hooks/compatibility/openers checkpoints (like --judge-only)",
    )
    args = parser.parse_args(argv)

    frames_dir = args.frames_dir.resolve()
    extract_dir = frames_dir / "extract"

    print("=" * 60)
    print("OFFLINE RESUME VALIDATION")
    print("=" * 60)
    print(f"RUN_MODE={config.RUN_MODE} HUMAN_APPROVAL={config.HUMAN_APPROVAL} "
          f"AUTO_ACTION={config.AUTO_ACTION}")
    print(f"Backend={config.JUDGE_BACKEND} model={config.OLLAMA_MODEL}")
    print(f"Frames dir: {frames_dir}")
    print(f"Extract dir: {extract_dir}\n")

    # Pre-flight cache inventory
    partials = sorted(extract_dir.glob("frame_*.json"))
    merged = extract_dir / "merged.json"
    hooks = extract_dir / "hooks.json"
    compat = extract_dir / "compatibility.json"
    openers = extract_dir / "openers.json"

    print("Cache inventory:")
    print(f"  frame partials : {len(partials)} files {'✓' if partials else '✗'}")
    print(f"  merged.json    : {'✓' if merged.is_file() else '✗'}")
    print(f"  hooks.json     : {'✓' if hooks.is_file() else '— (will run)'}")
    print(f"  compatibility  : {'✓' if compat.is_file() else '— (will run)'}")
    print(f"  openers.json   : {'✓' if openers.is_file() else '— (will run)'}")
    print()

    if not merged.is_file():
        print("ERROR: merged.json missing. Run --merge-only first.")
        return 1

    if hinge_actions_allowed():
        print("ERROR: Hinge actions would be allowed — refusing.")
        return 1

    frames = _load_frames(frames_dir)
    aryan_ctx = self_profile_summary(load_cached_self_profile())

    # Track Ollama calls
    ollama_calls: list[dict] = []
    import wingman.llm as llm_mod

    orig_text = llm_mod.text_json
    orig_vision = llm_mod.vision_json

    def tracked_text_json(system, user, **kwargs):
        t0 = time.monotonic()
        label = kwargs.pop("_label", "text_json")
        result = orig_text(system, user, **kwargs)
        elapsed = time.monotonic() - t0
        ollama_calls.append({
            "type": "text",
            "label": label,
            "seconds": round(elapsed, 1),
            "user_chars": len(user),
            "num_predict": kwargs.get("num_predict"),
        })
        return result

    def tracked_vision_json(system, user, frames_arg, **kwargs):
        t0 = time.monotonic()
        result = orig_vision(system, user, frames_arg, **kwargs)
        elapsed = time.monotonic() - t0
        ollama_calls.append({
            "type": "vision",
            "label": "vision_json",
            "seconds": round(elapsed, 1),
            "frames": len(frames_arg),
        })
        return result

    llm_mod.text_json = tracked_text_json  # type: ignore[assignment]
    llm_mod.vision_json = tracked_vision_json  # type: ignore[assignment]

    # Patch stage modules that imported text_json directly
    import wingman.hooks as hooks_mod
    import wingman.compatibility as compat_mod
    import wingman.opener as opener_mod

    def wrap_text(label):
        def _wrapped(system, user, **kwargs):
            kwargs["_label"] = label
            return tracked_text_json(system, user, **kwargs)
        return _wrapped

    hooks_mod.text_json = wrap_text("hooks")
    compat_mod.text_json = wrap_text("compatibility")
    opener_mod.text_json = wrap_text("openers")

    print("Running pipeline (no live capture)…\n")
    t_total = time.monotonic()
    try:
        rec = run_pipeline(
            frames,
            aryan_hinge_context=aryan_ctx,
            extract_dir=extract_dir,
            judge_only=False,
            resume_checkpoints=not args.force_downstream,
        )
    except Exception as exc:
        print(f"\nERROR: pipeline failed: {exc}")
        return 1
    finally:
        llm_mod.text_json = orig_text  # type: ignore[assignment]
        llm_mod.vision_json = orig_vision  # type: ignore[assignment]

    total_elapsed = time.monotonic() - t_total

    print("\n" + "=" * 60)
    print("VALIDATION REPORT")
    print("=" * 60)

    vision_calls = [c for c in ollama_calls if c["type"] == "vision"]
    text_calls = [c for c in ollama_calls if c["type"] == "text"]

    print(f"\nTotal wall time: {total_elapsed:.1f}s")
    print(f"Ollama vision calls: {len(vision_calls)}")
    print(f"Ollama text calls:   {len(text_calls)}")
    for call in ollama_calls:
        print(f"  - {call['label']}: {call['seconds']}s")

    if vision_calls:
        print("\n⚠ WARNING: vision calls were made (expected 0)")
    else:
        print("\n✓ No vision calls (cached frames reused)")

    print(f"\nProfile: {rec.profile.name}, age={rec.profile.age}, "
          f"location={rec.profile.location}")
    print(f"Profile effort: {rec.profile.profile_effort}")
    print(f"Prompts: {len(rec.profile.prompts)}, Photos: {len(rec.profile.photo_contexts)}")

    print("\nHooks extracted:")
    for h in rec.profile.hooks:
        print(f"  [tier {h.tier}] {h.label}: {h.detail[:80]}")

    c = rec.compatibility
    print(f"\nCompatibility: {c.decision.upper()} (confidence {c.confidence_score}/10)")
    for w in c.why[:4]:
        print(f"  - {w}")

    print("\nOpeners:")
    styles_seen = set()
    for o in rec.openers:
        styles_seen.add(o.style)
        valid_mark = "✓" if o.valid else f"✗ ({o.rejection_reason})"
        print(f"  [{o.style}] {valid_mark}")
        print(f"    text: {o.text}")
        print(f"    hook: {o.hook_used}")
        print(f"    evidence: {o.evidence}")
        # Re-validate evidence grounding
        grounded, reason = _validate_opener(
            o.text, o.hook_used + " " + o.evidence + " " + (rec.profile.best_hook().detail if rec.profile.best_hook() else "")
        )
        print(f"    grounded: {'yes' if grounded else 'no — ' + reason}")

    expected_styles = {"playful", "clever", "flirty"}
    missing_styles = expected_styles - styles_seen
    if missing_styles:
        print(f"\n⚠ Missing opener styles: {', '.join(sorted(missing_styles))}")
    elif len(rec.openers) == 3:
        print("\n✓ All 3 opener styles present")

    print(f"\nRecommended: {rec.recommended_style} — {rec.recommended_reason}")
    print(f"Hinge interaction attempted: NO")
    print(f"Token usage: in={rec.total_usage.get('input_tokens', 0)} "
          f"out={rec.total_usage.get('output_tokens', 0)}")

    print("\n--- Full recommendation ---")
    print_recommendation(rec)

    # Post-run checkpoint state
    print("\nCheckpoints written:")
    for name in ("merged.json", "hooks.json", "compatibility.json", "openers.json"):
        path = extract_dir / name
        print(f"  {name}: {'✓' if path.is_file() else '—'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
