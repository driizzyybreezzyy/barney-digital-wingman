"""Deterministic merge of per-frame profile extractions (no LLM)."""

from __future__ import annotations

import re
from typing import Any

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


def _norm(text: str) -> str:
    return " ".join(str(text).lower().split())


def _scrub_evidence(bullets: list[str]) -> list[str]:
    cleaned: list[str] = []
    for b in bullets:
        if any(m in b for m in _LEAK_MARKERS):
            continue
        cleaned.append(b)
    return cleaned


def _pick_name(partials: list[tuple[int, dict[str, Any]]]) -> str:
    from wingman.profile_clean import clean_extracted_name

    counts: dict[str, int] = {}
    for _idx, partial in partials:
        name = clean_extracted_name(str(partial.get("name") or ""))
        if name != "unknown":
            counts[name] = counts.get(name, 0) + 1
    if not counts:
        return "unknown"
    return max(counts, key=lambda k: counts[k])


def _pick_age(partials: list[tuple[int, dict[str, Any]]]) -> int | None:
    for _idx, partial in partials:
        age = partial.get("age")
        if isinstance(age, (int, float)) and int(age) > 0:
            return int(age)
    return None


def _pick_location(partials: list[tuple[int, dict[str, Any]]]) -> str:
    best = ""
    for _idx, partial in partials:
        loc = str(partial.get("location") or "").strip()
        if len(loc) > len(best):
            best = loc
    return best


def _pick_basic_info(partials: list[tuple[int, dict[str, Any]]]) -> str:
    parts: list[str] = []
    seen: set[str] = set()
    for _idx, partial in partials:
        info = str(partial.get("basic_info") or "").strip()
        if not info:
            continue
        key = _norm(info)
        if key in seen:
            continue
        seen.add(key)
        parts.append(info)
    return " | ".join(parts)


def _merge_prompts(
    partials: list[tuple[int, dict[str, Any]]],
) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    for frame_idx, partial in partials:
        for item in partial.get("prompts") or []:
            if not isinstance(item, dict):
                continue
            prompt_text = str(item.get("prompt_text") or "").strip()
            answer = str(item.get("answer") or "").strip()
            if not prompt_text and not answer:
                continue
            key = _norm(prompt_text) if prompt_text else _norm(answer)
            if key not in by_key:
                by_key[key] = {
                    "prompt_text": prompt_text,
                    "answer": answer,
                    "readable": bool(item.get("readable", True)),
                    "source_frames": [frame_idx],
                }
                order.append(key)
                continue
            existing = by_key[key]
            if len(answer) > len(existing["answer"]):
                existing["answer"] = answer
            if prompt_text and len(prompt_text) > len(existing["prompt_text"]):
                existing["prompt_text"] = prompt_text
            existing["readable"] = existing["readable"] or bool(item.get("readable", True))
            if frame_idx not in existing["source_frames"]:
                existing["source_frames"].append(frame_idx)

    return [by_key[k] for k in order]


def _merge_photos(
    partials: list[tuple[int, dict[str, Any]]],
) -> list[dict[str, Any]]:
    photos: list[dict[str, Any]] = []
    seen: set[str] = set()

    for frame_idx, partial in partials:
        for item in partial.get("photo_contexts") or []:
            if not isinstance(item, dict):
                continue
            desc = str(item.get("description") or "").strip()
            if not desc:
                continue
            key = _norm(desc)
            if key in seen:
                continue
            seen.add(key)
            photos.append({
                "index": len(photos) + 1,
                "description": desc,
                "source_frames": [frame_idx],
            })

    return photos


def _merge_string_list(
    partials: list[tuple[int, dict[str, Any]]],
    field: str,
) -> tuple[list[str], list[dict[str, Any]]]:
    values: list[str] = []
    seen: set[str] = set()
    sourced: list[dict[str, Any]] = []

    for frame_idx, partial in partials:
        for raw in partial.get(field) or []:
            text = str(raw).strip()
            if not text:
                continue
            key = _norm(text)
            if key in seen:
                continue
            seen.add(key)
            values.append(text)
            sourced.append({"text": text, "source_frame": frame_idx})

    return values, sourced


def _profile_effort(prompt_count: int, photo_count: int, signal_count: int) -> str:
    if prompt_count >= 3 and photo_count >= 3:
        return "high"
    if prompt_count >= 1 or photo_count >= 2 or signal_count >= 3:
        return "medium"
    if prompt_count == 0 and photo_count <= 1 and signal_count == 0:
        return "low"
    return "unknown"


def _deterministic_summary(merged: dict[str, Any]) -> str:
    parts: list[str] = []
    name = merged.get("name")
    age = merged.get("age")
    location = merged.get("location")
    if name and name != "unknown":
        label = str(name)
        if age:
            label += f", {age}"
        parts.append(label)
    if location:
        parts.append(f"from {location}")
    prompt_count = merged.get("prompt_count", 0)
    photo_count = merged.get("photo_count", 0)
    parts.append(f"{prompt_count} prompt(s), {photo_count} photo context(s)")
    effort = merged.get("profile_effort", "unknown")
    parts.append(f"profile effort: {effort}")
    return ". ".join(parts) + "."


def merge_partials(
    partials: list[tuple[int, dict[str, Any]]],
    *,
    frame_count: int | None = None,
) -> dict[str, Any]:
    """Merge ordered (frame_index, partial_json) pairs into one profile dict."""
    if not partials:
        raise ValueError("merge_partials requires at least one partial")

    prompts = _merge_prompts(partials)
    photos = _merge_photos(partials)
    interests, interest_sources = _merge_string_list(partials, "interest_signals")
    bullets, bullet_sources = _merge_string_list(partials, "evidence_bullets")
    bullets = _scrub_evidence(bullets)
    bullet_sources = [
        item for item in bullet_sources if not any(m in item["text"] for m in _LEAK_MARKERS)
    ]

    source_frames = sorted({idx for idx, _ in partials})
    merged: dict[str, Any] = {
        "name": _pick_name(partials),
        "age": _pick_age(partials),
        "location": _pick_location(partials),
        "basic_info": _pick_basic_info(partials),
        "prompts": prompts,
        "photo_contexts": photos,
        "interest_signals": interests,
        "interest_sources": interest_sources,
        "evidence_bullets": bullets,
        "evidence_sources": bullet_sources,
        "profile_effort": _profile_effort(len(prompts), len(photos), len(interests)),
        "photo_count": len(photos),
        "prompt_count": len(prompts),
        "source_frames": source_frames,
        "frames_merged": frame_count if frame_count is not None else len(source_frames),
        "merge_method": "deterministic_python",
    }
    merged["summary"] = _deterministic_summary(merged)
    return merged
