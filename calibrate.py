"""Screenshot + auto-detect tap targets for config.COORDS.

Hinge like flow:
  Discover → black circle + white heart on photo/prompt (bottom-right)
  Tap heart → "Add a comment" + Send Like
  Type comment → tap Send Like

Usage:
  Pass 1 — profile scrolled to photo 1 on Discover:
    .venv/bin/python calibrate.py

  Pass 2 — YOU tap the black heart on photo 1 (do NOT send), then:
    .venv/bin/python calibrate.py --compose
"""

from __future__ import annotations

import argparse
from pathlib import Path

import adb
import config
import vision
from coords_util import REF_SCREEN_HEIGHT, REF_SCREEN_WIDTH


def _device_to_ref(x: int, y: int) -> tuple[int, int]:
    rx = int(round(x * REF_SCREEN_WIDTH / config.SCREEN_WIDTH))
    ry = int(round(y * REF_SCREEN_HEIGHT / config.SCREEN_HEIGHT))
    return rx, ry


def _analyze(png: bytes, *, compose: bool) -> dict[str, tuple[int, int] | None]:
    out: dict[str, tuple[int, int] | None] = {
        "skip_button": None,
        "heart_photo_1": None,
        "send_like_button": None,
        "comment_input": None,
    }
    on_compose = vision.is_compose_screen(png)
    if compose and not on_compose:
        return out
    if compose or on_compose:
        out["send_like_button"] = vision.find_send_like(png)
        if out["send_like_button"]:
            out["comment_input"] = vision.find_comment_input(out["send_like_button"])
        return out
    out["skip_button"] = vision.find_skip_button(png)
    out["heart_photo_1"] = vision.find_first_heart(png)
    return out


def _print_results(
    path: Path,
    found: dict[str, tuple[int, int] | None],
    *,
    compose: bool,
    on_compose: bool,
) -> None:
    print(f"Saved: {path}")
    print(f"Screen: {config.SCREEN_WIDTH}x{config.SCREEN_HEIGHT}")
    print()
    if compose:
        if on_compose:
            print("Detected COMPOSE (Add a comment + Send Like):")
        else:
            print("Expected COMPOSE but screen still looks like DISCOVER.")
            print("(Black heart on photo — you must TAP it on the phone first.)")
    else:
        print("Detected DISCOVER (photo 1 at top):")
    print()
    any_found = False
    for key in ("skip_button", "heart_photo_1", "send_like_button", "comment_input"):
        xy = found.get(key)
        if xy is None:
            continue
        any_found = True
        ref = _device_to_ref(xy[0], xy[1])
        print(f"  {key}:")
        print(f"    device ({xy[0]}, {xy[1]})  ->  _COORDS_REF {ref}")
    print()
    if compose and not on_compose:
        print("  On phone: tap the BLACK circle heart on photo 1 (bottom-right).")
        print("  Wait for 'Add a comment' — then re-run:")
        print("    .venv/bin/python calibrate.py --compose")
    elif not any_found:
        print("  Could not auto-detect — scroll to photo 1 and retry.")
    else:
        print("Values detected. config.py COORDS already set from prior calibration;")
        print("re-run after a layout change or if assist-send still misses taps.")
    print()
    if not compose:
        print("Next: tap black heart on photo 1 (do NOT send), then:")
        print("  .venv/bin/python calibrate.py --compose")


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate Hinge tap coordinates")
    parser.add_argument(
        "--compose",
        action="store_true",
        help="After YOU tap heart: screenshot Add a comment + Send Like screen",
    )
    args = parser.parse_args()

    adb.check_device()
    png = adb.screenshot()
    on_compose = vision.is_compose_screen(png)
    suffix = "compose" if args.compose else "discover"
    path = Path(__file__).parent / f"calibrate_{suffix}.png"
    path.write_bytes(png)
    if args.compose:
        (Path(__file__).parent / "calibrate.png").write_bytes(png)

    found = _analyze(png, compose=args.compose)
    _print_results(path, found, compose=args.compose, on_compose=on_compose)


if __name__ == "__main__":
    main()
