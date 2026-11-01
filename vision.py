"""Image-based detection for UI elements whose position varies per profile.

The compose box (Send Like button + comment input) anchors to whichever
element's heart was tapped, so its absolute y coordinate shifts based on
photo height and scroll state. Static COORDS in config don't survive
across profiles — we have to find these elements at tap-time.
"""

import io

import numpy as np
from PIL import Image
from scipy.ndimage import label, find_objects


def _png_to_array(png: bytes) -> np.ndarray:
    return np.array(Image.open(io.BytesIO(png)).convert("RGB"))


def find_send_like(png: bytes) -> tuple[int, int] | None:
    """Locate the peach 'Send Like' pill on the compose card."""
    arr = _png_to_array(png)
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    peach = (
        (r > 220) & (g > 190) & (g < 235) & (b > 170) & (b < 220)
        & (r > g) & (g > b)
    )
    labeled, _ = label(peach)
    candidates = []
    for i, sl in enumerate(find_objects(labeled), 1):
        if sl is None:
            continue
        y0, y1 = sl[0].start, sl[0].stop
        x0, x1 = sl[1].start, sl[1].stop
        h, w = y1 - y0, x1 - x0
        area = (labeled[sl] == i).sum()
        if not (500 < w < 700 and 80 < h < 150 and area > 30000):
            continue
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        if cx <= 500:
            continue
        candidates.append((cy, cx))
    if not candidates:
        return None
    candidates.sort()
    cy, cx = candidates[0]
    return (cx, cy)


def is_compose_screen(png: bytes) -> bool:
    """True when Send Like / comment compose card is open."""
    return find_send_like(png) is not None or find_comment_field(png) is not None


def is_discover_profile(png: bytes) -> bool:
    """True when a Hinge profile card (heart or skip) is visible."""
    return find_first_heart(png) is not None or find_skip_button(png) is not None


def find_comment_field(png: bytes) -> tuple[int, int] | None:
    """Locate the gray 'Add a comment' input bar on the compose card."""
    arr = _png_to_array(png)
    gray = arr.mean(axis=2)
    light = (
        (arr[..., 0] > 175)
        & (arr[..., 1] > 175)
        & (arr[..., 2] > 175)
        & (gray < 248)
    )
    labeled, _ = label(light)
    candidates: list[tuple[int, int, int]] = []
    for i, sl in enumerate(find_objects(labeled), 1):
        if sl is None:
            continue
        y0, y1 = sl[0].start, sl[0].stop
        x0, x1 = sl[1].start, sl[1].stop
        h, w = y1 - y0, x1 - x0
        area = int((labeled[sl] == i).sum())
        if not (45 < h < 130 and w > 350 and area > 8000):
            continue
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        if cy < 900 or cy > 2200:
            continue
        candidates.append((cy, cx, w))
    if not candidates:
        return None
    cy, cx, _ = sorted(candidates)[0]
    return (cx, cy)


def find_skip_button(png: bytes) -> tuple[int, int] | None:
    """Locate the white circular X (skip) on the left of the profile card."""
    arr = _png_to_array(png)
    width = arr.shape[1]
    gray = arr.mean(axis=2)
    bright = gray > 215
    labeled, _ = label(bright)
    candidates: list[tuple[int, int, int]] = []
    for i, sl in enumerate(find_objects(labeled), 1):
        if sl is None:
            continue
        y0, y1 = sl[0].start, sl[0].stop
        x0, x1 = sl[1].start, sl[1].stop
        h, w = y1 - y0, x1 - x0
        area = int((labeled[sl] == i).sum())
        if not (70 < h < 220 and 70 < w < 220 and area > 2500):
            continue
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        if cx >= width * 0.42 or cy < 1100:
            continue
        # X mark inside the circle
        inner = gray[y0 + h // 4 : y1 - h // 4, x0 + w // 4 : x1 - w // 4]
        if inner.size == 0:
            continue
        if (inner < 120).sum() < 40:
            continue
        candidates.append((cy, cx, area))
    if not candidates:
        return None
    cy, cx, _ = sorted(candidates)[0]
    return (cx, cy)


def _hinge_heart_circles(arr: np.ndarray) -> list[tuple[int, int]]:
    """Black circle + white heart outline on photos/prompts (Hinge like button)."""
    width, height = arr.shape[1], arr.shape[0]
    gray = arr.mean(axis=2)
    hearts: list[tuple[int, int]] = []

    # Connected dark blobs (solid circles on some profiles).
    dark = gray < 78
    labeled, _ = label(dark)
    for i, sl in enumerate(find_objects(labeled), 1):
        if sl is None:
            continue
        y0, y1 = sl[0].start, sl[0].stop
        x0, x1 = sl[1].start, sl[1].stop
        h, w = y1 - y0, x1 - x0
        area = int((labeled[sl] == i).sum())
        if not (55 < h < 200 and 55 < w < 200 and area > 2200):
            continue
        if abs(w - h) > 35:
            continue
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        if cx <= width * 0.52 or cy < 900:
            continue
        iy0 = y0 + max(1, h // 5)
        iy1 = y1 - max(1, h // 5)
        ix0 = x0 + max(1, w // 5)
        ix1 = x1 - max(1, w // 5)
        inner = gray[iy0:iy1, ix0:ix1]
        if inner.size and int((inner > 195).sum()) >= 60:
            hearts.append((cy, cx))

    # Ring hearts: white outline splits the dark blob into fragments.
    hearts.extend(_scan_heart_rings(gray))
    # Dedupe nearby hits.
    uniq: list[tuple[int, int]] = []
    for cy, cx in sorted(hearts):
        if not any(abs(cy - y) < 40 and abs(cx - x) < 40 for y, x in uniq):
            uniq.append((cy, cx))
    return uniq


def _scan_heart_rings(gray: np.ndarray) -> list[tuple[int, int]]:
    """Grid search for dark ring + bright heart center (outline splits blob)."""
    height, width = gray.shape
    hits: list[tuple[int, int, float]] = []
    for cy in range(1100, min(height - 80, 2150), 18):
        for cx in range(int(width * 0.62), width - 40, 18):
            score = _heart_ring_score(gray, cx, cy)
            if score >= 0.55:
                hits.append((cy, cx, score))
    if not hits:
        return []
    hits.sort(key=lambda t: (-t[2], t[0]))
    best: list[tuple[int, int]] = []
    for cy, cx, _ in hits:
        if any(abs(cy - y) < 50 and abs(cx - x) < 50 for y, x in best):
            continue
        best.append((cy, cx))
        if len(best) >= 6:
            break
    return best


def _heart_ring_score(gray: np.ndarray, cx: int, cy: int) -> float:
    """Score how much a point looks like Hinge's black circle + white heart."""
    outer_r, inner_r = 46, 22
    ring_dark = 0
    ring_total = 0
    center_bright = 0
    center_total = 0
    for dy in range(-outer_r, outer_r + 1):
        for dx in range(-outer_r, outer_r + 1):
            dist = (dx * dx + dy * dy) ** 0.5
            x, y = cx + dx, cy + dy
            if y < 0 or y >= gray.shape[0] or x < 0 or x >= gray.shape[1]:
                continue
            g = gray[y, x]
            if outer_r - 10 <= dist <= outer_r + 4:
                ring_total += 1
                if g < 95:
                    ring_dark += 1
            elif dist <= inner_r:
                center_total += 1
                if g > 185:
                    center_bright += 1
    if ring_total < 80 or center_total < 40:
        return 0.0
    ring_frac = ring_dark / ring_total
    center_frac = center_bright / center_total
    if ring_frac < 0.45 or center_frac < 0.12:
        return 0.0
    return 0.6 * ring_frac + 0.4 * center_frac


def find_first_heart(png: bytes) -> tuple[int, int] | None:
    """Locate the topmost like heart (black circle, white outline) in view."""
    arr = _png_to_array(png)
    width = arr.shape[1]
    hearts = _hinge_heart_circles(arr)
    min_cx = int(width * 0.65)
    content = [(cy, cx) for cy, cx in hearts if 1050 < cy < 2250 and cx >= min_cx]
    if content:
        cy, cx = sorted(content)[0]
        return (cx, cy)
    # Legacy: solid white heart blobs (older Hinge builds / emulators).
    min_cx = int(width * 0.62)
    legacy = _collect_white_heart_blobs(arr, min_cx=min_cx, strict=True)
    if legacy:
        cy, cx = sorted(legacy)[0]
        return (cx, cy)
    legacy = _collect_white_heart_blobs(arr, min_cx=int(width * 0.55), strict=False)
    if legacy:
        cy, cx = sorted(legacy)[0]
        return (cx, cy)
    return None


def _collect_white_heart_blobs(
    arr: np.ndarray,
    *,
    min_cx: int,
    strict: bool,
) -> list[tuple[int, int]]:
    mask = (arr[..., 0] > 235) & (arr[..., 1] > 235) & (arr[..., 2] > 235)
    labeled, _ = label(mask)
    hearts: list[tuple[int, int]] = []
    for i, sl in enumerate(find_objects(labeled), 1):
        if sl is None:
            continue
        y0, y1 = sl[0].start, sl[0].stop
        x0, x1 = sl[1].start, sl[1].stop
        h, w = y1 - y0, x1 - x0
        area = (labeled[sl] == i).sum()
        if strict:
            if not (100 < h < 140 and 100 < w < 140):
                continue
            if abs(w - h) >= 15:
                continue
            if area < 8500 or area > 12000:
                continue
        else:
            if not (80 < h < 160 and 80 < w < 160):
                continue
            if area < 6000 or area > 15000:
                continue
        cx = (x0 + x1) // 2
        if cx <= min_cx:
            continue
        cy = (y0 + y1) // 2
        hearts.append((cy, cx))
    return hearts


def comment_field_text_pixels(png: bytes, send_like_xy: tuple[int, int]) -> int:
    """Count dark (text) pixels in the comment input area above Send Like.

    Empty field shows only faint grey placeholder ('Add a comment') — very
    few dark pixels. A filled field has many dark pixels from typed text.
    Used to verify that `adb shell input text` actually landed before
    Send Like fires (events can drop under host CPU contention).
    """
    arr = _png_to_array(png)
    sx, sy = send_like_xy
    y0 = max(0, sy - 230)
    y1 = max(0, sy - 60)
    x0 = max(0, sx - 350)
    x1 = min(arr.shape[1], sx + 350)
    region = arr[y0:y1, x0:x1]
    if region.size == 0:
        return 0
    dark = (region.max(axis=-1) < 130).sum()
    return int(dark)


def find_comment_input(send_like_xy: tuple[int, int]) -> tuple[int, int]:
    """Comment input sits at a fixed offset above the Send Like button.

    Measured offset across two profiles: ~171px above, x ~540 (centered
    in the compose card, not aligned with Send Like). Stable because the
    compose card's internal layout is fixed; only the whole card shifts.
    """
    _, send_y = send_like_xy
    return (540, send_y - 171)
