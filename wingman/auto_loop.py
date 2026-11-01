"""Automated Discover loop: capture → Wingman pipeline → like/skip on phone."""

from __future__ import annotations

import time
from pathlib import Path

import adb
import config
from wingman.approval import print_recommendation
from wingman.automation_guard import LikeBudget
from wingman.capture import _content_hash, capture_discover_profile, save_frames
from wingman.dry_run_report import build_report, print_dry_run_report, save_dry_run_report
from wingman.execute_action import execute_on_hinge, pick_opener_text
from wingman.experiment import new_profile_id
from wingman.pipeline import run_pipeline


def run_automated_session(
    *,
    aryan_hinge_context: str | None,
    max_profiles: int | None = None,
    single_frame: bool = False,
    dry_run: bool = False,
) -> dict:
    """Run capture → judge → (optional) tap loop until cap or max profiles."""
    serial = adb.check_device()
    max_p = max_profiles or config.MAX_PROFILES_PER_SESSION
    budget = LikeBudget()

    if dry_run:
        print(f"ADB: {serial}")
        print("DRY-RUN VALIDATION — capture + analysis only")
        print("  • NO like / skip / heart / send-comment taps")
        print("  • Profile scroll + screenshots OK (read profile for analysis)")
        print(f"  • Max profiles this run: {max_p}")
        print("Hinge must be open on Discover. Starting in 5s…")
    else:
        mode_label = "LIVE (will tap Hinge)"
        print(f"ADB: {serial}")
        print(f"Automated Wingman [{mode_label}] — max {budget.max_likes} likes, up to {max_p} profiles")
        print("Hinge must be open on Discover. Starting in 5s…")
    time.sleep(5)

    likes_sent = 0
    skips = 0
    profiles_seen = 0
    last_frame0_hash: str | None = None
    dry_run_reports: list[dict] = []

    while profiles_seen < max_p:
        if not dry_run and budget.exhausted:
            print(f"\nDaily like cap ({budget.max_likes}) reached. Stopping.")
            break

        profiles_seen += 1
        print(f"\n{'=' * 40}\nProfile {profiles_seen}/{max_p}\n{'=' * 40}")

        if single_frame:
            frames = [adb.screenshot()]
        else:
            frames = capture_discover_profile()

        frame0_hash = _content_hash(frames[0])
        if frame0_hash == last_frame0_hash:
            print("DUPLICATE: same profile as last iteration — would force skip (no tap in dry-run)")
            if not dry_run:
                from main import do_skip

                try:
                    do_skip()
                except Exception as e:
                    print(f"Skip failed: {e!r}")
                    break
            time.sleep(2)
            continue
        last_frame0_hash = frame0_hash

        out = save_frames(frames, prefix="wingman_profile")
        extract_dir = out / "extract"
        print(f"Saved: {out} ({len(frames)} frames, new timestamped dir)")

        print(f"Running pipeline on {len(frames)} frame(s)...")
        rec = run_pipeline(
            frames,
            aryan_hinge_context=aryan_hinge_context,
            extract_dir=extract_dir,
            resume_checkpoints=not dry_run,
        )
        merged_data = None
        merged_path = extract_dir / "merged.json"
        if merged_path.is_file():
            import json

            merged_data = json.loads(merged_path.read_text(encoding="utf-8"))
        print_recommendation(rec)

        profile_id = new_profile_id()
        opener_text, opener_style = pick_opener_text(rec)
        hook_used = rec.compatibility.best_hook_label
        for o in rec.openers or []:
            if o.style == opener_style:
                hook_used = o.hook_used
                break

        if dry_run:
            report = build_report(
                rec,
                opener_text=opener_text,
                opener_style=opener_style,
                hook_used=hook_used,
                frames_dir=out,
                frame_count=len(frames),
                merged=merged_data,
            )
            saved = save_dry_run_report(report, extract_dir)
            print_dry_run_report(report)
            print(f"Dry-run artifact saved: {saved}")
            dry_run_reports.append(report)
            # No execute_on_hinge — zero decision taps
            if report["decision"]["effective"] == "LIKE":
                likes_sent += 1
            else:
                skips += 1
        else:
            result = execute_on_hinge(
                rec,
                profile_id=profile_id,
                budget=budget,
                frames_dir=str(out),
                dry_run=False,
            )
            action = result.get("action")
            if action == "cap_reached":
                break
            if result.get("like_sent"):
                likes_sent += 1
            elif action in ("skip", "skip_no_opener"):
                skips += 1

        print(
            f"Session tally: {likes_sent} would-like/liked, {skips} would-skip/skipped, "
            f"{budget.remaining()} likes remaining"
        )
        if dry_run:
            break  # one validation profile per dry-run invocation
        time.sleep(2)

    summary = {
        "profiles_seen": profiles_seen,
        "likes_sent": likes_sent,
        "skips": skips,
        "likes_remaining": budget.remaining(),
        "dry_run": dry_run,
        "reports": dry_run_reports,
    }
    print(f"\nAutomated session done: {summary}")
    return summary
