"""Coordinate scaling and device helpers."""

from __future__ import annotations

# Reference resolution the shipped tap targets were calibrated against.
REF_SCREEN_WIDTH = 1080
REF_SCREEN_HEIGHT = 2424


def scale_coords(
    base: dict,
    width: int,
    height: int,
    *,
    ref_width: int = REF_SCREEN_WIDTH,
    ref_height: int = REF_SCREEN_HEIGHT,
) -> dict:
    """Scale pixel coords from reference screen to target device."""
    sx = width / ref_width
    sy = height / ref_height
    out: dict = {}
    for key, value in base.items():
        if key == "scroll_duration_ms":
            out[key] = value
            continue
        if isinstance(value, tuple) and len(value) == 2:
            x, y = value
            out[key] = (int(round(x * sx)), int(round(y * sy)))
        else:
            out[key] = value
    return out


def bottom_nav_x(slot_index: int, width: int, *, slots: int = 5) -> int:
    """Center x of bottom-nav slot (0=Discover … 4=Profile)."""
    return int(round(width / slots * (slot_index + 0.5)))
