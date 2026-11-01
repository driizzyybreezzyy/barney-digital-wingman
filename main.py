"""HingeAuto orchestrator.

Loop: capture profile frames -> ask Claude -> tap like or skip -> repeat.
"""

import argparse
import hashlib
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

import io

from PIL import Image

import adb
import config
import metrics
import vision
from judge_common import load_backend

judge = load_backend().judge


def _profile_region_hash(png: bytes) -> str:
    """md5 over a cropped region of the frame, excluding status bar (clock
    ticks every minute) and bottom nav (badges flicker). Two screenshots
    of the same profile taken 60+ seconds apart should produce the same
    hash; two different profiles should always differ."""
    img = Image.open(io.BytesIO(png))
    w, h = img.size
    crop = img.crop((0, 120, w, h - 220))
    return hashlib.md5(crop.tobytes()).hexdigest()


def capture_profile() -> list[bytes]:
    """Scroll through the current profile, returning a list of PNG frames."""
    # Defensive: new profiles load at the top, so this is just guarding
    # against the app being mid-scroll from a prior partial action. A
    # handful of swipes is enough — full 18-swipe sweep isn't needed
    # because we aren't recovering from a 7-frame scroll-down.
    scroll_back_to_top(swipes=5)

    frames = []
    frames.append(adb.screenshot())
    adb.jitter_sleep("after_screenshot")

    for _ in range(config.FRAMES_PER_PROFILE - 1):
        adb.scroll_down()
        adb.jitter_sleep("after_scroll")
        frames.append(adb.screenshot())
        adb.jitter_sleep("after_screenshot")

    return frames


def scroll_back_to_top(swipes: int | None = None) -> None:
    """Scroll back to the top of the profile.

    Hinge uses momentum scrolling; each swipe's actual travel is much less
    than the gesture's pixel distance. Default `swipes` is `FRAMES_PER_PROFILE
    * 2 + 4` (18 with FRAMES=7) — enough to recover from a full scroll-down
    through the profile. Pass a smaller `swipes` for defensive top-scrolls
    where the profile is already at or near the top.
    """
    if swipes is None:
        swipes = config.FRAMES_PER_PROFILE * 2 + 4
    for _ in range(swipes):
        adb.scroll_up()
        adb.jitter_sleep("after_scroll")


def _run_mode_label() -> str:
    mode = getattr(config, "RUN_MODE", "automated").lower()
    labels = {
        "dry_run": "DRY RUN (capture + judge, no taps)",
        "wingman": "WINGMAN (approval required)",
        "assisted": "ASSISTED (approval, then bot acts)",
        "automated": "AUTOMATED",
    }
    if mode not in labels:
        raise ValueError(
            f"Unknown RUN_MODE={mode!r}. Use dry_run, wingman, assisted, or automated."
        )
    suffix = ""
    if mode == "automated" and config.DRY_RUN:
        suffix = " + legacy DRY_RUN (force-skip likes)"
    elif mode == "automated" and not config.DRY_RUN:
        suffix = " + LIVE (will tap)"
    return labels[mode] + suffix


def _should_perform_actions() -> bool:
    """Whether this run mode may tap Skip / Like on Hinge."""
    mode = getattr(config, "RUN_MODE", "automated").lower()
    if mode == "dry_run":
        return False
    if mode == "wingman":
        return False  # Phase 2 adds approval + manual send
    if mode == "assisted":
        return bool(getattr(config, "AUTO_ACTION", False))
    if mode == "automated":
        return True
    raise ValueError(f"Unknown RUN_MODE={mode!r}")


def _wait_for_manual_advance() -> bool:
    """Pause between dry-run profiles. Returns False if user wants to quit."""
    try:
        answer = input(
            "\n[dry-run] Advance to the next profile in the emulator, "
            "then press Enter (or q to quit): "
        ).strip().lower()
    except EOFError:
        return False
    return answer not in ("q", "quit", "exit")


def do_skip() -> None:
    """Tap the X to advance to the next profile. Always taps (even in dry run);
    advancing is needed for the loop to see new profiles."""
    x, y = config.COORDS["skip_button"]
    adb.tap(x, y)
    adb.jitter_sleep("after_skip")


def _resolve_heart_tap() -> tuple[int, int]:
    """Find photo-1 heart: vision first, calibrated COORDS fallback."""
    if getattr(config, "PROFILE_AT_TOP_AFTER_CAPTURE", False):
        scroll_back_to_top(swipes=4)
        config.PROFILE_AT_TOP_AFTER_CAPTURE = False
    else:
        scroll_back_to_top()
    for attempt in range(3):
        heart_xy = vision.find_first_heart(adb.screenshot())
        if heart_xy is not None:
            print(f"  [like] heart found at {heart_xy}")
            return heart_xy
        if attempt < 2:
            print(f"  [like] heart not found — scroll to top retry {attempt + 2}/3")
            scroll_back_to_top(swipes=8)
    fallback = config.COORDS.get("heart_photo_1")
    if fallback:
        print("  WARN: vision heart miss — tapping calibrated heart_photo_1 COORDS")
        return int(fallback[0]), int(fallback[1])
    debug_path = config.DEBUG_DIR / "assist_send_heart_miss.png"
    debug_path.parent.mkdir(parents=True, exist_ok=True)
    debug_path.write_bytes(adb.screenshot())
    raise RuntimeError(
        f"vision: couldn't find photo-1 heart after scroll-back "
        f"(screenshot saved: {debug_path}). "
        "Run: .venv/bin/python calibrate.py — then update config COORDS for your phone."
    )


def _wait_for_compose(timeout_s: float = 10.0) -> tuple[int, int] | None:
    """Wait for Send Like button after heart tap (= compose card open)."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        png = adb.screenshot()
        xy = vision.find_send_like(png)
        if xy is not None:
            return xy
        if vision.find_comment_field(png) is not None:
            fallback = config.COORDS.get("send_like_button")
            if fallback:
                return (int(fallback[0]), int(fallback[1]))
        time.sleep(0.7)
    return None


def _open_compose(heart_xy: tuple[int, int]) -> tuple[int, int]:
    """Tap heart until Add a comment / Send Like appears."""
    for attempt in range(3):
        adb.tap(*heart_xy)
        adb.jitter_sleep("after_tap")
        send_xy = _wait_for_compose()
        if send_xy is not None:
            print(f"  [like] compose open — Send Like at {send_xy}")
            return send_xy
        if attempt < 2:
            print(f"  [like] compose not open — heart retry {attempt + 2}/3")
    debug_path = config.DEBUG_DIR / "assist_send_compose_miss.png"
    debug_path.parent.mkdir(parents=True, exist_ok=True)
    debug_path.write_bytes(adb.screenshot())
    raise RuntimeError(
        f"compose card did not open after heart taps (saved {debug_path}). "
        "Phone must show this profile at photo 1. Paste comment manually."
    )


def do_like(message: str = "") -> dict:
    """Tap heart, type message, send like. Returns {verified, warnings}."""
    if config.DRY_RUN:
        do_skip()
        return {"verified": False, "warnings": ["dry_run skip"]}

    warnings: list[str] = []
    heart_xy = _resolve_heart_tap()
    send_xy = _open_compose(heart_xy)

    png = adb.screenshot()
    comment_xy = vision.find_comment_field(png) or vision.find_comment_input(send_xy)
    text_verified = not bool(message.strip())

    if message:
        adb.tap(*comment_xy)
        adb.jitter_sleep("after_tap")
        empty_pixels = vision.comment_field_text_pixels(adb.screenshot(), send_xy)
        adb.input_text(message)
        deadline = time.monotonic() + 18
        target_pixels = empty_pixels + max(150, 20 * len(message))
        current = empty_pixels
        while time.monotonic() < deadline:
            time.sleep(0.8)
            current = vision.comment_field_text_pixels(adb.screenshot(), send_xy)
            if current >= target_pixels * 0.92:
                text_verified = True
                break
        else:
            warnings.append(
                f"comment may not have typed (pixels {current}/{target_pixels})"
            )
            print(f"  WARN: {warnings[-1]}")
        post_type_xy = vision.find_send_like(adb.screenshot())
        if post_type_xy is not None:
            send_xy = post_type_xy
    adb.tap(*send_xy)
    adb.jitter_sleep("after_like_sent")

    verified = text_verified
    if not verified:
        debug_path = config.DEBUG_DIR / "assist_send_after_tap.png"
        debug_path.parent.mkdir(parents=True, exist_ok=True)
        debug_path.write_bytes(adb.screenshot())
        warnings.append(f"check phone manually (debug {debug_path})")
    return {"verified": verified, "warnings": warnings}


def save_debug(frames: list[bytes], decision, profile_idx: int) -> None:
    if not config.SAVE_DEBUG_FRAMES:
        return
    bucket = "liked" if decision.decision == "like" else "skipped"
    bucket_dir = config.DEBUG_DIR / bucket
    bucket_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^a-z0-9]", "", (decision.name or "unknown").lower()) or "unknown"
    folder = bucket_dir / f"{profile_idx:02d}_{safe_name}"
    imgs = folder / "imgs"
    imgs.mkdir(parents=True, exist_ok=True)
    for i, png in enumerate(frames):
        (imgs / f"frame_{i:02d}.png").write_bytes(png)
    (folder / "decision.txt").write_text(
        f"name: {decision.name}\n"
        f"decision: {decision.decision}\n"
        f"confidence: {decision.confidence}\n"
        f"reasoning: {decision.reasoning}\n"
        f"message: {decision.message}\n"
        f"message_archetype: {decision.message_archetype}\n"
        f"prompt_referenced: {decision.prompt_referenced}\n"
        f"skip_reason: {decision.skip_reason}\n"
        f"timestamp: {datetime.now().isoformat(timespec='seconds')}\n"
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="HingeAuto loop runner")
    p.add_argument(
        "--mode",
        default=None,
        help="Override config.ACTIVE_MODE for this run (one-shot). "
             "Must match a file under modes/<name>.py.",
    )
    p.add_argument(
        "--set-filters",
        action="store_true",
        help="Before looping, drive the in-app age slider to match the "
             "active mode's AGE_MIN/AGE_MAX. Requires filter_coords.json "
             "(see calibrate_filters.py).",
    )
    p.add_argument(
        "--location",
        default=None,
        help="Before looping, change Hinge's 'My neighborhood' to the "
             "named city (resolved via locations.json). Orthogonal to "
             "--mode. Requires location_coords.json + Hinge+/X for "
             "out-of-area changes.",
    )
    p.add_argument(
        "--rotate",
        default=None,
        help="Named rotation path from locations.json _rotations (e.g. "
             "'atl'). When Hinge's 'You've seen everyone' screen appears, "
             "advance to the next city in the rotation. Loops back to "
             "start when exhausted.",
    )
    p.add_argument(
        "--run-mode",
        default=None,
        choices=("dry_run", "wingman", "assisted", "automated"),
        help="Override config.RUN_MODE for this run.",
    )
    return p.parse_args(argv)


def main() -> int:
    args = _parse_args()
    load_dotenv()

    if args.mode:
        config.ACTIVE_MODE = args.mode
        config._apply_mode()
    if args.run_mode:
        config.RUN_MODE = args.run_mode

    serial = adb.check_device()
    print(f"Connected to: {serial}")
    age_band = (
        f"age {config.AGE_MIN}-{config.AGE_MAX}"
        if (config.AGE_MIN is not None or config.AGE_MAX is not None)
        else "no age gate"
    )
    print(f"Mode:     {config.MODE_NAME} ({age_band})")
    print(f"Run:      {_run_mode_label()}")
    if getattr(config, "HUMAN_APPROVAL", False):
        print("Approval: HUMAN_APPROVAL enabled")
    print(f"Max likes: {config.MAX_LIKES_PER_SESSION}, "
          f"max profiles: {config.MAX_PROFILES_PER_SESSION}")

    if args.set_filters:
        if config.AGE_MIN is None and config.AGE_MAX is None:
            print("--set-filters requested but active mode has no age range; "
                  "skipping in-app filter step.")
        else:
            import filters
            print(f"Setting in-app age filter to {config.AGE_MIN}-{config.AGE_MAX}...")
            filters.set_age_range(config.AGE_MIN, config.AGE_MAX)

    if args.location:
        import locations
        resolved = locations.resolve(args.location)
        print(f"Setting location to '{args.location}' (search: '{resolved}')...")
        locations.set_location(args.location)

    rotation_list: list[str] | None = None
    rotation_idx: int = 0
    if args.rotate:
        import locations
        rotation_list = locations.get_rotation(args.rotate)
        # If --location was also set, start the rotation at that location if
        # it's in the list; otherwise prepend it (don't replace the rotation).
        if args.location and args.location in rotation_list:
            rotation_idx = rotation_list.index(args.location)
        print(f"Rotation '{args.rotate}': {rotation_list} (starting at "
              f"index {rotation_idx} = '{rotation_list[rotation_idx]}')")

    print("Starting in 5s. Make sure Hinge is open on the Discover tab.")
    time.sleep(5)

    likes_sent = 0
    skips = 0
    profiles_seen = 0
    total_cost = 0.0
    total_seconds = 0.0
    last_frame0_hash: str | None = None
    duplicate_streak = 0

    while profiles_seen < config.MAX_PROFILES_PER_SESSION:
        profiles_seen += 1
        print(f"\n--- Profile {profiles_seen} ---")

        t0 = time.monotonic()
        frames = capture_profile()
        t_capture = time.monotonic() - t0
        print(f"Captured {len(frames)} frames")

        # Out-of-candidates detection: if frame 0 shows the "You've seen
        # everyone for now" screen, we're stuck. If --rotate is on, advance
        # to the next city; otherwise just break since further iteration
        # would just force-skip nothing.
        if rotation_list is not None:
            import locations
            if locations.is_out_of_candidates(frames[0]):
                rotation_idx = (rotation_idx + 1) % len(rotation_list)
                next_city = rotation_list[rotation_idx]
                print(f"OUT OF CANDIDATES — rotating to '{next_city}' "
                      f"(index {rotation_idx}/{len(rotation_list) - 1}).")
                try:
                    locations.set_location(next_city)
                except Exception as e:
                    print(f"set_location failed: {e!r} — continuing in place.")
                last_frame0_hash = None
                duplicate_streak = 0
                profiles_seen -= 1  # don't count the empty-state capture
                continue

        # If frame 0 is identical to the previous profile's frame 0, Hinge
        # didn't advance after our last action — force-skip rather than
        # burning another ~$0.035 re-judging the same person. Escalate the
        # delay if we keep duplicating, in case Hinge needs a beat to
        # recover from an "out of likes" / popup state.
        #
        # Hash a cropped region of frame 0 (excluding status bar at top and
        # nav bar at bottom). The status-bar clock ticks every minute and
        # the nav-bar can show transient badges; both make raw-bytes md5
        # diverge across iterations even when the *profile* is identical,
        # which silently breaks duplicate detection. Cropping isolates the
        # part of the screen that actually identifies the profile.
        frame0_hash = _profile_region_hash(frames[0])
        if frame0_hash == last_frame0_hash:
            duplicate_streak += 1
            print(f"DUPLICATE: frame 0 matches previous profile "
                  f"(streak {duplicate_streak}).")
            if _should_perform_actions():
                print("Force-skipping without judge.")
                try:
                    do_skip()
                except Exception as e:
                    print(f"Skip failed during duplicate recovery: {e!r}")
                time.sleep(min(2 + duplicate_streak * 2, 15))
            else:
                print("[dry-run] Still on the same profile — advance manually "
                      "in the emulator.")
                if not _wait_for_manual_advance():
                    break
            continue
        last_frame0_hash = frame0_hash
        duplicate_streak = 0

        t1 = time.monotonic()
        decision = None
        fatal_error = None
        for attempt in range(3):
            try:
                decision = judge(frames)
                break
            except Exception as e:
                err = repr(e)
                print(f"Judge attempt {attempt + 1}/3 failed: {e}")
                # Halt on errors that won't recover with a retry — burning
                # through Hinge swipes blind (force-skipping every profile
                # without a real decision) eats the daily quota and looks
                # robotic to Hinge. Saw this once when the Anthropic credit
                # balance hit zero mid-run: 124 profiles got blindly skipped
                # before we noticed.
                if any(s in err for s in (
                    "credit balance is too low",
                    "authentication_error",
                    "invalid_api_key",
                    "permission_error",
                )):
                    fatal_error = err
                    break
                if attempt < 2:
                    time.sleep(5 * (attempt + 1))
        if fatal_error is not None:
            print(f"\nFATAL judge error — halting loop instead of burning "
                  f"Hinge swipes:\n  {fatal_error}")
            break
        t_judge = time.monotonic() - t1
        if decision is None:
            print("Judge failed 3 times — skipping this profile to keep the loop alive.")
            if _should_perform_actions():
                do_skip()
            elif not _wait_for_manual_advance():
                break
            continue

        print(f"Name:     {decision.name}")
        print(f"Decision: {decision.decision} ({decision.confidence}) "
              f"[{decision.skip_reason if decision.decision == 'skip' else decision.message_archetype}]")
        print(f"Reason:   {decision.reasoning}")
        if decision.message:
            print(f"Message:  {decision.message}")
        save_debug(frames, decision, profiles_seen)

        t2 = time.monotonic()
        if not _should_perform_actions():
            print("[dry-run] No Hinge action taken.")
            if config.RUN_MODE == "dry_run" and not _wait_for_manual_advance():
                break
        elif decision.decision == "like":
            if likes_sent >= config.MAX_LIKES_PER_SESSION:
                print(f"Hit max likes cap ({config.MAX_LIKES_PER_SESSION}). Stopping.")
                break
            try:
                do_like(decision.message)
                likes_sent += 1
            except Exception as e:
                print(f"do_like failed: {e!r} — recovering by skipping this profile.")
                try:
                    do_skip()
                except Exception as e2:
                    print(f"do_skip recovery also failed: {e2!r} — loop will retry next iter.")
                skips += 1
        else:
            do_skip()
            skips += 1
        t_act = time.monotonic() - t2

        timing = {
            "capture_seconds": round(t_capture, 2),
            "judge_seconds":   round(t_judge, 2),
            "act_seconds":     round(t_act, 2),
            "total_seconds":   round(t_capture + t_judge + t_act, 2),
        }
        metrics.log_profile(profiles_seen, decision, timing)
        total_cost += metrics.estimated_cost(decision.usage)
        total_seconds += timing["total_seconds"]
        metrics.print_running_totals(
            profiles_seen, likes_sent, skips, total_cost, total_seconds,
        )

    print(f"\nDone. {likes_sent} likes sent across {profiles_seen} profiles.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
