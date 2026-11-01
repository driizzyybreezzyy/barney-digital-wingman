"""Digital Wingman session — full profile scroll + optional self-scan.

Usage:
  # First time: scan YOUR Hinge profile (photos + prompts) ~15-25 min
  .venv/bin/python wingman_session.py --self-scan

  # Full IRL: capture → approve → bot types comment on Hinge
  .venv/bin/python wingman_session.py --production

  # Same but you paste manually (no bot typing)
  .venv/bin/python wingman_session.py --production --manual-send

  # Single-screen capture (faster, partial)
  .venv/bin/python wingman_session.py --live-capture --single-frame --no-approval

Safety: scroll-only during capture. With --production, bot sends like+comment
after you approve (1/2/3/e). Use --manual-send to paste yourself instead.
Self-scan uses nav taps only to open your View tab, then scroll+capture.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

import config
from wingman.approval import print_production_preflight, print_recommendation, run_approval
from wingman.capture import capture_discover_profile, save_frames
from wingman.experiment import new_profile_id
from wingman.pipeline import run_pipeline
from wingman.platforms import SUPPORTED_PLATFORMS
from wingman.self_profile import (
    capture_and_cache_self_profile,
    load_cached_self_profile,
    self_profile_summary,
)


def _assert_safe(args: argparse.Namespace) -> None:
    if getattr(args, "automate_dry_run", False):
        config.RUN_MODE = "automated"
        config.DRY_RUN = True
        return
    if getattr(args, "automate", False):
        if getattr(args, "live_actions", False):
            raise SystemExit(
                "Live Hinge actions are DISABLED for this experiment phase.\n"
                "Use --automate-dry-run to validate capture + judgment only.\n"
                "Human must send every like/comment on phone until dry-runs are reviewed."
            )
        raise SystemExit(
            "Use --automate-dry-run for validation, or --automate --live-actions "
            "(live actions blocked until experiment review)."
        )
    if config.RUN_MODE != "dry_run" and not config.HUMAN_APPROVAL:
        raise SystemExit("Refusing: HUMAN_APPROVAL must be True")


def _load_images_from_dir(path: Path) -> list[bytes]:
    files = sorted(path.glob("frame_*.png"))
    if not files:
        raise FileNotFoundError(f"No frame_*.png in {path}")
    return [f.read_bytes() for f in files]


def _frames_setting(single: bool, *, fast: bool = False) -> int:
    from wingman.personality import load_preferences

    prefs = load_preferences()
    if single:
        return 1
    n = int(prefs.get("discover_profile_frames") or config.FRAMES_PER_PROFILE)
    if fast:
        return min(10, n)
    return n


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Digital Wingman session")
    parser.add_argument("--image", type=Path, help="Single offline PNG fixture")
    parser.add_argument(
        "--frames-dir",
        type=Path,
        help="Directory with frame_00.png ... from a prior capture",
    )
    parser.add_argument(
        "--live-capture",
        action="store_true",
        help="Capture from phone (full scroll by default)",
    )
    parser.add_argument(
        "--single-frame",
        action="store_true",
        help="Capture/analyze one screen only (fast, partial)",
    )
    parser.add_argument(
        "--self-scan",
        action="store_true",
        help="Navigate to YOUR profile View tab, scroll-capture, cache to data/",
    )
    parser.add_argument(
        "--self-scan-analyze",
        type=Path,
        metavar="FRAMES_DIR",
        help="Analyze saved self-profile frames only (no phone taps). "
             "Example: debug/self_profile_20260902_002332",
    )
    parser.add_argument(
        "--no-approval",
        action="store_true",
        help="Print recommendation only",
    )
    parser.add_argument(
        "--production",
        action="store_true",
        help="IRL pipeline: capture + approve + send comment (bot types after approval)",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Cap capture at 6 frames",
    )
    parser.add_argument(
        "--platform",
        choices=SUPPORTED_PLATFORMS,
        default="generic",
        help="Platform label for analysis; does not automate that platform",
    )
    parser.add_argument(
        "--manual-send",
        action="store_true",
        help="With --production: log only, you paste on phone (no bot typing)",
    )
    parser.add_argument(
        "--assist-send",
        action="store_true",
        help="After approval, bot taps heart and types comment (sets assisted mode)",
    )
    parser.add_argument(
        "--judge-only",
        action="store_true",
        help="Skip vision+merge; use extract/merged.json from --frames-dir",
    )
    parser.add_argument(
        "--merge-only",
        action="store_true",
        help="Offline: deterministic merge from cached frame JSON; writes merged.json",
    )
    parser.add_argument(
        "--force-downstream",
        action="store_true",
        help="Ignore hooks/compatibility/openers checkpoints; re-run downstream stages",
    )
    parser.add_argument(
        "--openers-only",
        action="store_true",
        help="Regenerate openers only from cached merged/hooks/compatibility",
    )
    parser.add_argument(
        "--automate",
        action="store_true",
        help="Loop: capture → judge → auto like/skip on phone",
    )
    parser.add_argument(
        "--automate-dry-run",
        action="store_true",
        help="Same as automate but prints actions only — no Hinge taps",
    )
    parser.add_argument(
        "--live-actions",
        action="store_true",
        help="Required with --automate (not dry-run) — bot taps Hinge",
    )
    parser.add_argument(
        "--max-profiles",
        type=int,
        default=None,
        help=f"Max profiles per automated session (default {config.MAX_PROFILES_PER_SESSION})",
    )
    args = parser.parse_args(argv)

    if args.production:
        args.live_capture = True
        args.no_approval = False
        if not args.manual_send:
            args.assist_send = True

    if args.live_capture and args.platform != "hinge":
        raise SystemExit(
            "Live ADB capture is currently Hinge-only. For Bumble, Tinder, "
            "Happn, or another platform, provide saved screenshots with "
            "--frames-dir and select --platform."
        )

    if getattr(args, "fast", False):
        config.DISCOVER_PROFILE_MAX_FRAMES = min(10, config.DISCOVER_PROFILE_MAX_FRAMES)
        config.FRAMES_PER_PROFILE = min(10, config.FRAMES_PER_PROFILE)

    if getattr(args, "assist_send", False):
        config.RUN_MODE = "assisted"
        config.DRY_RUN = False
        config.AUTO_ACTION = True

    if getattr(args, "assist_send", False) and args.judge_only and args.frames_dir:
        raise SystemExit(
            "assist-send + judge-only is unreliable (phone may not match cached profile).\n"
            "Use: .venv/bin/python wingman_session.py --production\n"
            "Or re-capture with --live-capture --assist-send (not --judge-only)."
        )

    if args.automate_dry_run:
        args.automate = True

    _assert_safe(args)
    print("Digital Wingman")
    print(f"RUN_MODE={config.RUN_MODE} HUMAN_APPROVAL={config.HUMAN_APPROVAL} "
          f"AUTO_ACTION={config.AUTO_ACTION} DRY_RUN={config.DRY_RUN}")
    print(f"Backend={config.JUDGE_BACKEND} model={config.OLLAMA_MODEL}")
    if args.automate:
        print(f"MAX_LIKES={config.MAX_LIKES_PER_SESSION} PREFER_ACTIVE_NOW={config.PREFER_ACTIVE_NOW}")
    print()

    if args.automate:
        from wingman.auto_loop import run_automated_session

        cached = load_cached_self_profile()
        aryan_ctx = self_profile_summary(cached)
        run_automated_session(
            aryan_hinge_context=aryan_ctx,
            max_profiles=args.max_profiles,
            single_frame=args.single_frame,
            dry_run=args.automate_dry_run,
        )
        return 0

    if args.self_scan_analyze:
        from wingman.self_profile import analyze_cached_self_profile

        analyze_cached_self_profile(args.self_scan_analyze)
        print("\nSelf-profile analysis complete (from saved frames).")
        return 0

    if args.merge_only:
        if not args.frames_dir:
            raise SystemExit("--merge-only requires --frames-dir")
        from wingman.profile_analyzer import merge_cached_partials

        frames = sorted(args.frames_dir.glob("frame_*.png"))
        if not frames:
            raise SystemExit(f"No frame_*.png in {args.frames_dir}")
        extract_dir = args.frames_dir / "extract"
        merged = merge_cached_partials(extract_dir, expected_frames=len(frames))
        print(f"\nMerge complete: name={merged.get('name')}, age={merged.get('age')}, "
              f"prompts={merged.get('prompt_count')}, photos={merged.get('photo_count')}")
        print(f"Saved: {extract_dir / 'merged.json'}")
        return 0

    if args.openers_only:
        if not args.frames_dir:
            raise SystemExit("--openers-only requires --frames-dir")
        from wingman.pipeline import run_openers_only

        frames = _load_images_from_dir(args.frames_dir)
        extract_dir = args.frames_dir / "extract"
        print(f"Mode: openers-only (regenerate openers.json, ~1-3 min)\n")
        rec = run_openers_only(frames, extract_dir=extract_dir)
        if args.no_approval:
            print_recommendation(rec)
        print("\nOpeners regenerated. Discover skip/like/comment attempted: NO")
        return 0

    if args.self_scan:
        n = _frames_setting(single=False)
        print(f"[self-scan] ETA: ~{n * 2 + 3} min with qwen2.5vl:3b")
        print("Hinge: opens YOUR profile View tab, scrolls, returns to Discover.")
        print("No likes/skips on other profiles.\n")
        capture_and_cache_self_profile(n_frames=n)
        print("\nSelf-scan complete. Re-run with --live-capture to analyze matches.")
        return 0

    cached = load_cached_self_profile()
    if not cached:
        print("NOTE: No cached self-profile yet. Run once:")
        print("  .venv/bin/python wingman_session.py --self-scan\n")
    else:
        print(f"Using cached self-profile from {cached.get('captured_at', '?')}\n")

    aryan_ctx = self_profile_summary(cached)

    extract_dir: Path | None = None
    if args.live_capture:
        import adb

        if args.production:
            print_production_preflight(assist_send=getattr(args, "assist_send", False))
        serial = adb.check_device()
        n = _frames_setting(args.single_frame, fast=getattr(args, "fast", False))
        if args.single_frame:
            print(f"ADB: {serial} — single screenshot")
            png = adb.screenshot()
            frames = [png]
            out = save_frames(frames, prefix="wingman_single")
        else:
            print(f"ADB: {serial} — scrolling full profile ({n} frames)")
            print("Hinge: scroll within profile ONLY (no skip/like/comment)")
            eta_min = n * 2 + 4
            print(f"ETA: ~{eta_min} min with qwen2.5vl:3b\n")
            frames = capture_discover_profile(n)
            out = save_frames(frames, prefix="wingman_profile")
            if getattr(args, "assist_send", False) or args.production:
                from wingman.capture import scroll_to_top

                print("[capture] Scrolling back to top — phone ready for assist-send…")
                scroll_to_top(max_swipes=14)
                config.PROFILE_AT_TOP_AFTER_CAPTURE = True
        extract_dir = out / "extract"
        print(f"Saved: {out}\n")
    elif args.frames_dir:
        frames = _load_images_from_dir(args.frames_dir)
        extract_dir = args.frames_dir / "extract"
        cached_partials = sum(
            1 for i in range(len(frames)) if (extract_dir / f"frame_{i:02d}.json").is_file()
        )
        has_merged = (extract_dir / "merged.json").is_file()
        print(f"Using {len(frames)} frames from {args.frames_dir}")
        if args.judge_only:
            if not has_merged:
                raise SystemExit(
                    f"No extract/merged.json in {args.frames_dir}. "
                    "Run without --judge-only first."
                )
            print("Mode: judge-only (skip vision, ~5-10 min)\n")
            if getattr(args, "assist_send", False):
                print(
                    "⚠ assist-send + judge-only: phone MUST still show THIS profile\n"
                    "  on Discover, scrolled to the top, before you pick 1/2/3/c.\n"
                    "  Prefer --production (capture + send in one session).\n"
                )
        elif cached_partials == len(frames) and has_merged:
            print("Extract cache complete — vision+merge skipped (~5-10 min for hooks/judge)\n")
        elif cached_partials:
            remaining = len(frames) - cached_partials
            print(
                f"Extract cache: {cached_partials}/{len(frames)} frames — "
                f"~{remaining * 3} min remaining for vision\n"
            )
        else:
            eta_min = len(frames) * 3 + 4
            print(f"No extract cache — full vision ETA ~{eta_min} min\n")
        print()
    elif args.image:
        frames = [args.image.read_bytes()]
        print(f"Using fixture: {args.image}\n")
    else:
        default = config.DEBUG_DIR / "hinge_test.png"
        frames = [default.read_bytes()]
        print(f"Using fixture: {default}\n")

    print(f"Running pipeline on {len(frames)} frame(s)...")
    rec = run_pipeline(
        frames,
        aryan_hinge_context=aryan_ctx,
        extract_dir=extract_dir,
        judge_only=args.judge_only,
        resume_checkpoints=not args.force_downstream,
        platform=args.platform,
    )

    profile_id = new_profile_id()
    if args.no_approval:
        print_recommendation(rec)
        print("\nSession complete. Discover skip/like/comment attempted: NO")
        return 0

    frames_parent = str(extract_dir.parent) if extract_dir else ""

    while True:
        result = run_approval(
            rec,
            profile_id,
            assist_send=getattr(args, "assist_send", False),
            frames_dir=frames_parent,
        )
        if result.get("action") == "regenerate":
            from wingman.opener import generate_openers

            if rec.compatibility.decision == "like":
                openers, rs, rr = generate_openers(rec.profile, rec.compatibility)
                rec.openers = openers
                rec.recommended_style = rs
                rec.recommended_reason = rr
            continue
        break

    if result.get("action") == "approved":
        if result.get("send_failed"):
            print("\nSession complete. Send FAILED or unverified — paste comment on phone manually.")
        elif result.get("sent"):
            print("\nSession complete. Like + comment sent (verified on screen).")
        elif getattr(args, "assist_send", False):
            print("\nSession complete. Send unverified — check Hinge now.")
        else:
            print("\nSession complete. Logged — send manually on phone if you haven't.")
    elif result.get("action") == "skip" and getattr(args, "assist_send", False):
        print("\nSession complete. Skip sent on Hinge.")
    elif result.get("action") == "skip":
        print("\nSession complete. Logged SKIP — advance profile on phone.")
    else:
        print("\nAdvance to next profile on phone manually, then re-run.")
        print("Discover skip/like/comment attempted: NO")
    return 0


if __name__ == "__main__":
    sys.exit(main())
