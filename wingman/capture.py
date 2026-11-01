"""Safe multi-frame capture — human-like scroll, scroll-until-end."""

from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path

from PIL import Image

import adb
import config


def _content_hash(png: bytes) -> str:
    """Return a stable low-resolution fingerprint of profile content.

    Full-image hashes are too sensitive to scroll animations and text
    antialiasing, so compare a normalized grayscale thumbnail instead.
    """
    img = Image.open(io.BytesIO(png))
    w, h = img.size
    top = min(120, max(0, h // 4))
    bottom = max(top + 1, h - 220)
    crop = img.crop((0, top, w, bottom))
    crop.thumbnail((32, 32), Image.Resampling.BILINEAR)
    return crop.convert("L").tobytes()


def scroll_to_top(max_swipes: int = 12) -> None:
    for i in range(max_swipes):
        adb.scroll_up()
        adb.jitter_sleep("after_scroll")
        if i > 0 and i % 4 == 0:
            print(f"  scrolling to top… ({i}/{max_swipes})")


def ensure_discover_visible(*, max_backs: int = 4) -> None:
    """Dismiss overlays until a Hinge Discover profile is visible."""
    import vision

    for attempt in range(max_backs + 1):
        png = adb.screenshot()
        if vision.is_discover_profile(png):
            if attempt:
                print(f"[capture] Hinge profile visible after {attempt} back tap(s)")
            return
        if attempt >= max_backs:
            break
        print("[capture] Not on a profile (notifications open?) — pressing BACK…")
        adb.press_back()
        adb.jitter_sleep("after_tap")
    raise RuntimeError(
        "Hinge Discover profile not visible. Close notification shade, open Hinge "
        "on Discover, scroll to one profile, then re-run."
    )


def capture_scrolling_profile(
    *,
    max_frames: int | None = None,
    min_frames: int = 3,
    label: str = "profile",
) -> list[bytes]:
    """Scroll top→bottom with human-like swipes; stop when bottom reached."""
    max_f = max_frames or getattr(config, "DISCOVER_PROFILE_MAX_FRAMES", 8)
    max_f = max(1, max_f)
    min_f = min(min_frames, max_f)
    print(f"[capture] Scrolling through {label} (up to {max_f} frames, human-like swipes)…")
    ensure_discover_visible()
    scroll_to_top()

    frames: list[bytes] = []
    last_hash: str | None = None
    duplicate_streak = 0

    for i in range(max_f):
        png = adb.screenshot()
        h = _content_hash(png)
        if h == last_hash:
            duplicate_streak += 1
            if duplicate_streak >= 2 and len(frames) >= min_f:
                print("  reached bottom of profile (stable frame)")
                break
            if i < max_f - 1:
                adb.scroll_down()
                adb.jitter_sleep("after_scroll")
            continue

        frames.append(png)
        print(f"  frame {len(frames)} captured")
        adb.jitter_sleep("after_screenshot")

        duplicate_streak = 0
        last_hash = h

        if i < max_f - 1:
            adb.scroll_down()
            adb.jitter_sleep("after_scroll")

    print(f"[capture] Done — {len(frames)} frames")
    return frames


def capture_discover_profile(n_frames: int | None = None) -> list[bytes]:
    """Full Discover profile scroll — no skip/like."""
    max_f = n_frames or getattr(config, "DISCOVER_PROFILE_MAX_FRAMES", 8)
    return capture_scrolling_profile(max_frames=max_f, label="Discover profile")


def capture_self_profile(n_frames: int | None = None) -> list[bytes]:
    max_f = n_frames or getattr(config, "SELF_PROFILE_MAX_FRAMES", 8)
    return capture_scrolling_profile(max_frames=max_f, label="your profile")


def save_frames(frames: list[bytes], prefix: str = "wingman_profile") -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    folder = config.DEBUG_DIR / f"{prefix}_{stamp}"
    folder.mkdir(parents=True, exist_ok=True)
    for i, png in enumerate(frames):
        (folder / f"frame_{i:02d}.png").write_bytes(png)
    return folder
