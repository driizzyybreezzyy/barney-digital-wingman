"""Stage 1: extract structured profile evidence from screenshot(s)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from wingman.llm import vision_json
from wingman.merge_frames import merge_partials
from wingman.models import PhotoContext, ProfileAnalysis, PromptItem
from wingman.profile_cache import (
    load_all_partials,
    load_merged,
    load_partial,
    save_merged,
    save_partial,
)

_LEAK_MARKERS = (
    "Primary goals",
    "Secondary goals",
    "Banned phrases",
    "Opener avoid",
    "De-prioritize",
    "soft-boy",
    "Default boldness",
    "Aryan profile",
)

_FRAME_EXTRACT_SYSTEM = """You extract visible dating-profile content from ONE screenshot frame.
Extract ONLY what is visible in the dating app UI. Do not invent movies, quotes, or details not on screen.
Do not judge attractiveness. Describe photo context (activity/setting) only — never as a Hinge prompt.

Profile prompts have a SHORT prompt title and a SEPARATE answer below it. Never put the same text
in both fields. Never ask meta questions like
"What is the person's name/age/location/wearing?" — those are NOT Hinge prompts.

Do not capture onboarding UI ("Keep going", "We're learning who you like").
Do not copy JSON schema placeholders as the name (e.g. "lowercase first name or empty").
Do not summarize personality as a fake prompt (e.g. "shows thoughtful signals"). If text is not
clearly a Hinge prompt + answer on screen, omit it.

Respond with ONLY JSON:
{
  "name": "lowercase first name or empty",
  "age": null or integer,
  "location": "",
  "basic_info": "",
  "prompts": [{"prompt_text": "...", "answer": "...", "readable": true}],
  "photo_contexts": [{"index": 1, "description": "context only"}],
  "interest_signals": ["..."],
  "evidence_bullets": ["visible fact from this frame only"],
  "desirability_score": 5,
  "league_signals": ["e.g. high quality photos", "designer clothes", "social proof"]
}"""


def _scrub_evidence(bullets: list[str]) -> list[str]:
    cleaned = []
    for b in bullets:
        if any(m in b for m in _LEAK_MARKERS):
            continue
        cleaned.append(b)
    return cleaned


def _extract_single_frame(
    frame: bytes,
    index: int,
    total: int,
    platform: str = "generic",
) -> dict[str, Any]:
    user = (
        f"This is frame {index + 1} of {total} scrolling through one "
        f"{platform} dating profile "
        f"(top to bottom). Extract only what is visible in THIS frame."
    )
    data, _usage = vision_json(_FRAME_EXTRACT_SYSTEM, user, [frame])
    return data


def _merge_frames(partials: list[tuple[int, dict[str, Any]]], *, frame_count: int) -> dict[str, Any]:
    return merge_partials(partials, frame_count=frame_count)


def _build_analysis(data: dict[str, Any], usage: dict | None = None) -> ProfileAnalysis:
    prompts = [
        PromptItem(
            prompt_text=str(p.get("prompt_text", "")),
            answer=str(p.get("answer", "")),
            readable=bool(p.get("readable", True)),
        )
        for p in (data.get("prompts") or [])
        if isinstance(p, dict)
    ]
    photos = [
        PhotoContext(
            index=int(p.get("index", i + 1)),
            description=str(p.get("description", "")),
        )
        for i, p in enumerate(data.get("photo_contexts") or [])
        if isinstance(p, dict)
    ]
    age_raw = data.get("age")
    age = int(age_raw) if isinstance(age_raw, (int, float)) else None
    bullets = _scrub_evidence([str(x) for x in (data.get("evidence_bullets") or [])])

    return ProfileAnalysis(
        name=str(data.get("name") or "unknown").lower().strip() or "unknown",
        age=age,
        location=str(data.get("location") or ""),
        basic_info=str(data.get("basic_info") or ""),
        prompts=prompts,
        photo_contexts=photos,
        interest_signals=[str(x) for x in (data.get("interest_signals") or [])],
        profile_effort=str(data.get("profile_effort") or "unknown"),
        evidence_bullets=bullets,
        usage=usage or {},
        summary=str(data.get("summary") or ""),
        desirability_score=int(data.get("desirability_score") or 5),
        league_signals=[str(x) for x in (data.get("league_signals") or [])],
    )


def merge_cached_partials(
    extract_dir: Path,
    *,
    expected_frames: int,
) -> dict[str, Any]:
    """Deterministic merge from cached frame JSON; writes merged.json."""
    partials, errors = load_all_partials(extract_dir, expected_frames)
    for msg in errors:
        print(f"  [merge] warning: {msg}")
    if not partials:
        raise RuntimeError(
            f"No valid partials in {extract_dir}. "
            f"Errors: {'; '.join(errors) or 'none loaded'}"
        )
    print(f"  Merging {len(partials)} frame partial(s) (deterministic)…")
    merged = _merge_frames(partials, frame_count=expected_frames)
    save_merged(extract_dir, merged)
    print(f"  Wrote {extract_dir / 'merged.json'}")
    return merged


def analyze_profile(
    frames: list[bytes],
    *,
    extract_dir: Path | None = None,
    platform: str = "generic",
) -> ProfileAnalysis:
    if not frames:
        raise ValueError("analyze_profile requires at least one frame")

    if extract_dir:
        cached_merged = load_merged(extract_dir)
        if cached_merged:
            print(f"  Using cached merged profile from {extract_dir / 'merged.json'}")
            analysis = _build_analysis(cached_merged)
            analysis.frame_count = len(frames)
            return analysis

    if len(frames) == 1:
        partial = None
        if extract_dir:
            partial = load_partial(extract_dir, 0)
        if partial is None:
            print("  Analyzing frame 1/1…")
            partial = _extract_single_frame(frames[0], 0, 1, platform)
            if extract_dir:
                save_partial(extract_dir, 0, partial)
        merged = merge_partials([(0, partial)], frame_count=1)
        if extract_dir:
            save_merged(extract_dir, merged)
        analysis = _build_analysis(merged)
        analysis.frame_count = 1
        return analysis

    partials: list[tuple[int, dict[str, Any]]] = []
    load_errors: list[str] = []

    for i, frame in enumerate(frames):
        cached = load_partial(extract_dir, i) if extract_dir else None
        if cached is not None:
            print(f"  Using cached extract frame {i + 1}/{len(frames)}")
            partials.append((i, cached))
            continue
        print(f"  Analyzing frame {i + 1}/{len(frames)}…")
        partial = _extract_single_frame(frame, i, len(frames), platform)
        partials.append((i, partial))
        if extract_dir:
            save_partial(extract_dir, i, partial)

    print(f"  Merging {len(partials)} frame partial(s) (deterministic)…")
    merged = _merge_frames(partials, frame_count=len(frames))

    if extract_dir:
        save_merged(extract_dir, merged)

    analysis = _build_analysis(merged)
    analysis.frame_count = len(frames)
    return analysis


def profile_to_cache_dict(analysis: ProfileAnalysis, frames: int) -> dict[str, Any]:
    hooks = [h.label for h in analysis.hooks if h.tier <= 2] if analysis.hooks else []
    return {
        "captured_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "name": analysis.name,
        "photo_count": len(analysis.photo_contexts),
        "prompt_count": len(analysis.prompts),
        "profile_effort": analysis.profile_effort,
        "prompts": [
            {"prompt_text": p.prompt_text, "answer": p.answer} for p in analysis.prompts
        ],
        "photo_contexts": [
            {"index": p.index, "description": p.description} for p in analysis.photo_contexts
        ],
        "evidence_bullets": analysis.evidence_bullets,
        "conversation_hooks": hooks,
        "summary": getattr(analysis, "summary", ""),
        "frames_captured": frames,
        "desirability_score": getattr(analysis, "desirability_score", 5),
        "league_signals": getattr(analysis, "league_signals", []),
    }
