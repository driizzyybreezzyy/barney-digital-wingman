"""Capture and cache Aryan's live Hinge profile (photos + prompts)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import config
from scan_self import (
    capture_self_frames,
    navigate_to_self_view,
    return_to_discover,
)
from wingman.capture import save_frames
from wingman.profile_analyzer import analyze_profile, profile_to_cache_dict


CACHE_NAME = "aryan_hinge_profile.json"


def cache_path() -> Path:
    return getattr(config, "DATA_DIR", config.BASE_DIR / "data") / CACHE_NAME


def load_cached_self_profile() -> dict[str, Any] | None:
    path = cache_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def self_profile_summary(cached: dict[str, Any] | None) -> str:
    if not cached:
        return "(no live Hinge self-profile cached — run with --self-scan first)"
    lines = [
        f"Captured: {cached.get('captured_at', '?')}",
        f"Photos seen: {cached.get('photo_count', '?')}",
        f"Prompts seen: {cached.get('prompt_count', '?')}",
    ]
    for p in cached.get("prompts", [])[:6]:
        if isinstance(p, dict):
            lines.append(f"  Prompt: {p.get('prompt_text', '')}")
            lines.append(f"  Answer: {p.get('answer', '')}")
    hooks = cached.get("conversation_hooks", [])
    if hooks:
        lines.append("Your strongest hooks: " + ", ".join(str(h) for h in hooks[:3]))
    if cached.get("summary"):
        lines.append(f"Summary: {cached['summary']}")
    return "\n".join(lines)


def analyze_cached_self_profile(frames_dir: Path) -> dict[str, Any]:
    """Analyze already-captured self-profile frames (skip phone navigation)."""
    from wingman.hooks import extract_hooks

    files = sorted(frames_dir.glob("frame_*.png"))
    if not files:
        raise FileNotFoundError(f"No frames in {frames_dir}")
    frames = [f.read_bytes() for f in files]
    print(f"[self-scan] Analyzing {len(frames)} saved frames from {frames_dir}")
    print(f"[self-scan] ETA: ~{len(frames) * 2 + 2} min with qwen2.5vl:3b")
    analysis = analyze_profile(frames)
    extract_hooks(analysis)
    cached = profile_to_cache_dict(analysis, frames=len(frames))
    cached["source"] = "hinge_self_view"
    cached["frames_dir"] = str(frames_dir)
    cache_path().parent.mkdir(parents=True, exist_ok=True)
    cache_path().write_text(json.dumps(cached, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[self-scan] Cached: {cache_path()}")
    return cached


def capture_and_cache_self_profile(n_frames: int | None = None) -> dict[str, Any]:
    """Navigate to View tab, scroll-capture full self profile, analyze, cache."""
    import adb

    n = n_frames or getattr(config, "SELF_PROFILE_MAX_FRAMES", 14)
    serial = adb.check_device()
    print(f"[self-scan] Device: {serial}")
    print("[self-scan] Start on Discover tab, then we'll open YOUR View profile.")
    navigate_to_self_view(verify=True)

    print(f"[self-scan] Scrolling through your full profile (6 photos + prompts + video)…")
    frames = capture_self_frames(n)
    folder = save_frames(frames, prefix="self_profile")
    print(f"[self-scan] Saved frames: {folder}")

    print("[self-scan] Analyzing your photos + prompts with Ollama...")
    analysis = analyze_profile(frames)
    from wingman.hooks import extract_hooks

    extract_hooks(analysis)
    cached = profile_to_cache_dict(analysis, frames=len(frames))
    cached["source"] = "hinge_self_view"
    cached["frames_dir"] = str(folder)

    cache_path().parent.mkdir(parents=True, exist_ok=True)
    cache_path().write_text(json.dumps(cached, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[self-scan] Cached: {cache_path()}")

    print("[self-scan] Returning to Discover...")
    return_to_discover()
    return cached
