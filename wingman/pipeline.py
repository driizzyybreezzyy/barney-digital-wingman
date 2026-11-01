"""Orchestrate Wingman stages: analyze → hooks → compatibility → openers."""

from __future__ import annotations

import time
from pathlib import Path

from wingman.compatibility import evaluate_compatibility
from wingman.hooks import extract_hooks
from wingman.models import WingmanRecommendation
from wingman.opener import generate_openers
from wingman.profile_analyzer import analyze_profile
from wingman.profile_cache import (
    load_compatibility,
    load_hooks,
    load_merged,
    load_openers,
    profile_from_merged,
    save_compatibility,
    save_hooks,
    save_openers,
)
from wingman.self_profile import load_cached_self_profile, self_profile_summary
from wingman.platforms import normalize_platform


def run_pipeline(
    frames: list[bytes],
    *,
    aryan_hinge_context: str | None = None,
    extract_dir: Path | None = None,
    judge_only: bool = False,
    resume_checkpoints: bool = True,
    platform: str = "generic",
) -> WingmanRecommendation:
    platform = normalize_platform(platform)
    if not frames and not judge_only:
        raise ValueError("run_pipeline requires at least one screenshot frame")

    if aryan_hinge_context is None:
        cached = load_cached_self_profile()
        aryan_hinge_context = self_profile_summary(cached)

    use_downstream_cache = bool(
        resume_checkpoints and extract_dir and not judge_only
    )

    # --- Profile (vision + merge, or cached merged.json) ---
    if judge_only:
        if not extract_dir:
            raise ValueError("judge_only requires extract_dir")
        merged = load_merged(extract_dir)
        if not merged:
            raise FileNotFoundError(
                f"No merged.json in {extract_dir}. Run merge first (--merge-only or full pipeline)."
            )
        print("  [checkpoint] merged.json → SKIP MERGE")
        profile = profile_from_merged(merged, frame_count=len(frames) or 1)
        profile.platform = platform
    else:
        profile = analyze_profile(frames, extract_dir=extract_dir, platform=platform)
        profile.platform = platform
        profile.frame_count = len(frames)

    # --- Hooks ---
    if use_downstream_cache and extract_dir:
        cached_hooks = load_hooks(extract_dir)
        if cached_hooks:
            print("  [checkpoint] hooks.json → SKIP HOOKS")
            profile.hooks = cached_hooks
        else:
            print("  Hooks → RUN")
            t0 = time.monotonic()
            extract_hooks(profile)
            save_hooks(extract_dir, profile.hooks)
            print(f"  Hooks done ({time.monotonic() - t0:.1f}s)")
    else:
        print("  Hooks → RUN")
        t0 = time.monotonic()
        extract_hooks(profile)
        if extract_dir:
            save_hooks(extract_dir, profile.hooks)
        print(f"  Hooks done ({time.monotonic() - t0:.1f}s)")

    # --- Compatibility ---
    if use_downstream_cache and extract_dir:
        cached_compat = load_compatibility(extract_dir)
        if cached_compat:
            print("  [checkpoint] compatibility.json → SKIP COMPATIBILITY")
            compatibility = cached_compat
        else:
            print("  Compatibility → RUN")
            t0 = time.monotonic()
            compatibility = evaluate_compatibility(
                profile, aryan_hinge_context=aryan_hinge_context
            )
            save_compatibility(extract_dir, compatibility)
            print(f"  Compatibility done ({time.monotonic() - t0:.1f}s)")
    else:
        print("  Compatibility → RUN")
        t0 = time.monotonic()
        compatibility = evaluate_compatibility(
            profile, aryan_hinge_context=aryan_hinge_context
        )
        if extract_dir:
            save_compatibility(extract_dir, compatibility)
        print(f"  Compatibility done ({time.monotonic() - t0:.1f}s)")

    # --- Openers ---
    openers = []
    recommended_style = ""
    recommended_reason = ""
    if compatibility.decision == "like":
        if use_downstream_cache and extract_dir:
            cached_openers = load_openers(extract_dir)
            if cached_openers:
                print("  [checkpoint] openers.json → SKIP OPENERS")
                openers, recommended_style, recommended_reason = cached_openers
            else:
                print("  Openers → RUN")
                t0 = time.monotonic()
                openers, recommended_style, recommended_reason = generate_openers(
                    profile, compatibility
                )
                save_openers(
                    extract_dir, openers, recommended_style, recommended_reason
                )
                print(f"  Openers done ({time.monotonic() - t0:.1f}s)")
        else:
            print("  Openers → RUN")
            t0 = time.monotonic()
            openers, recommended_style, recommended_reason = generate_openers(
                profile, compatibility
            )
            if extract_dir:
                save_openers(
                    extract_dir, openers, recommended_style, recommended_reason
                )
            print(f"  Openers done ({time.monotonic() - t0:.1f}s)")
    else:
        print("  Openers → SKIP (decision=skip)")

    # Human production: still generate openers on SKIP so you can override with l/1/2/3
    import config as _cfg

    if (
        not openers
        and compatibility.decision == "skip"
        and getattr(_cfg, "HUMAN_APPROVAL", True)
        and profile.hooks
    ):
        from wingman.profile_clean import clean_prompts

        if clean_prompts(profile):
            print("  Openers → RUN (preview — SKIP decision, human may override)")
            t0 = time.monotonic()
            preview_compat = compatibility
            if preview_compat.decision != "like":
                from dataclasses import replace

                preview_compat = replace(preview_compat, decision="like")
            openers, recommended_style, recommended_reason = generate_openers(
                profile, preview_compat
            )
            if extract_dir:
                save_openers(extract_dir, openers, recommended_style, recommended_reason)
            print(f"  Openers preview done ({time.monotonic() - t0:.1f}s)")

    total_usage = {
        "input_tokens": profile.usage.get("input_tokens", 0)
        + compatibility.usage.get("input_tokens", 0),
        "output_tokens": profile.usage.get("output_tokens", 0)
        + compatibility.usage.get("output_tokens", 0),
    }

    return WingmanRecommendation(
        profile=profile,
        compatibility=compatibility,
        openers=openers,
        recommended_style=recommended_style,
        recommended_reason=recommended_reason,
        total_usage=total_usage,
    )


def run_openers_only(
    frames: list[bytes],
    *,
    extract_dir: Path,
) -> WingmanRecommendation:
    """Regenerate openers from cached merged/hooks/compatibility only."""
    merged = load_merged(extract_dir)
    if not merged:
        raise FileNotFoundError(f"No merged.json in {extract_dir}")

    print("  [openers-only] merged.json → SKIP MERGE/VISION")
    profile = profile_from_merged(merged, frame_count=len(frames) or 1)

    print("  [openers-only] hooks → REFRESH (cleaned prompts)")
    extract_hooks(profile)
    save_hooks(extract_dir, profile.hooks)

    compatibility = load_compatibility(extract_dir)
    if not compatibility:
        raise FileNotFoundError(f"No compatibility.json in {extract_dir}")
    print("  [openers-only] compatibility.json → LOAD (unchanged)")

    if compatibility.decision != "like":
        raise RuntimeError(
            f"Compatibility decision is {compatibility.decision!r}; openers require like"
        )

    print("  Openers → RUN")
    t0 = time.monotonic()
    openers, recommended_style, recommended_reason = generate_openers(
        profile, compatibility
    )
    save_openers(extract_dir, openers, recommended_style, recommended_reason)
    print(f"  Openers done ({time.monotonic() - t0:.1f}s) → saved openers.json")

    total_usage = {
        "input_tokens": profile.usage.get("input_tokens", 0)
        + compatibility.usage.get("input_tokens", 0),
        "output_tokens": profile.usage.get("output_tokens", 0)
        + compatibility.usage.get("output_tokens", 0),
    }

    return WingmanRecommendation(
        profile=profile,
        compatibility=compatibility,
        openers=openers,
        recommended_style=recommended_style,
        recommended_reason=recommended_reason,
        total_usage=total_usage,
    )
