"""Cache per-profile extraction (partials + merged) to avoid re-vision."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from wingman.models import (
    CompatibilityResult,
    ConversationHook,
    OpenerCandidate,
    PhotoContext,
    ProfileAnalysis,
    PromptItem,
)
from wingman.profile_clean import clean_extracted_name


def extract_dir_for(frames_dir: Path) -> Path:
    return frames_dir / "extract"


def load_all_partials(
    extract_dir: Path,
    expected: int,
) -> tuple[list[tuple[int, dict[str, Any]]], list[str]]:
    """Load frame partials; return (loaded, error_messages)."""
    loaded: list[tuple[int, dict[str, Any]]] = []
    errors: list[str] = []

    for i in range(expected):
        path = extract_dir / f"frame_{i:02d}.json"
        if not path.is_file():
            errors.append(f"frame_{i:02d}.json missing")
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"frame_{i:02d}.json malformed JSON: {exc}")
            continue
        except OSError as exc:
            errors.append(f"frame_{i:02d}.json unreadable: {exc}")
            continue
        if not isinstance(data, dict):
            errors.append(f"frame_{i:02d}.json is not a JSON object")
            continue
        loaded.append((i, data))

    return loaded, errors


def save_partial(extract_dir: Path, index: int, data: dict[str, Any]) -> None:
    extract_dir.mkdir(parents=True, exist_ok=True)
    (extract_dir / f"frame_{index:02d}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_partial(extract_dir: Path, index: int) -> dict[str, Any] | None:
    path = extract_dir / f"frame_{index:02d}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save_merged(extract_dir: Path, data: dict[str, Any]) -> None:
    extract_dir.mkdir(parents=True, exist_ok=True)
    (extract_dir / "merged.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_merged(extract_dir: Path) -> dict[str, Any] | None:
    path = extract_dir / "merged.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def profile_from_merged(data: dict[str, Any], frame_count: int = 1) -> ProfileAnalysis:
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
    hooks = [
        ConversationHook(
            label=str(h.get("label", "")),
            detail=str(h.get("detail", "")),
            tier=max(1, min(4, int(h.get("tier", 4)))),
            source=str(h.get("source", "")),
        )
        for h in (data.get("hooks") or [])
        if isinstance(h, dict)
    ]
    return ProfileAnalysis(
        name=clean_extracted_name(str(data.get("name") or "unknown")),
        age=age,
        location=str(data.get("location") or ""),
        basic_info=str(data.get("basic_info") or ""),
        prompts=prompts,
        photo_contexts=photos,
        interest_signals=[str(x) for x in (data.get("interest_signals") or [])],
        profile_effort=str(data.get("profile_effort") or "unknown"),
        evidence_bullets=[str(x) for x in (data.get("evidence_bullets") or [])],
        hooks=hooks,
        frame_count=frame_count,
        summary=str(data.get("summary") or ""),
    )


def _write_json(extract_dir: Path, name: str, data: dict[str, Any]) -> None:
    extract_dir.mkdir(parents=True, exist_ok=True)
    (extract_dir / name).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _read_json(extract_dir: Path, name: str) -> dict[str, Any] | None:
    path = extract_dir / name
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def save_hooks(extract_dir: Path, hooks: list[ConversationHook]) -> None:
    _write_json(
        extract_dir,
        "hooks.json",
        {
            "hooks": [
                {
                    "label": h.label,
                    "detail": h.detail,
                    "tier": h.tier,
                    "source": h.source,
                }
                for h in hooks
            ]
        },
    )


def load_hooks(extract_dir: Path) -> list[ConversationHook] | None:
    data = _read_json(extract_dir, "hooks.json")
    if not data:
        return None
    hooks: list[ConversationHook] = []
    for h in data.get("hooks") or []:
        if not isinstance(h, dict):
            continue
        hooks.append(
            ConversationHook(
                label=str(h.get("label", "")),
                detail=str(h.get("detail", "")),
                tier=max(1, min(4, int(h.get("tier", 4)))),
                source=str(h.get("source", "")),
            )
        )
    return hooks or None


def save_compatibility(extract_dir: Path, result: CompatibilityResult) -> None:
    _write_json(
        extract_dir,
        "compatibility.json",
        {
            "decision": result.decision,
            "confidence_score": result.confidence_score,
            "why": result.why,
            "compatibility_signals": result.compatibility_signals,
            "incompatibility_signals": result.incompatibility_signals,
            "best_hook_label": result.best_hook_label,
            "usage": result.usage,
        },
    )


def load_compatibility(extract_dir: Path) -> CompatibilityResult | None:
    data = _read_json(extract_dir, "compatibility.json")
    if not data:
        return None
    decision = str(data.get("decision", "skip")).lower()
    if decision not in ("like", "skip"):
        decision = "skip"
    return CompatibilityResult(
        decision=decision,
        confidence_score=max(1, min(10, int(data.get("confidence_score", 3)))),
        why=[str(x) for x in (data.get("why") or [])],
        compatibility_signals=[str(x) for x in (data.get("compatibility_signals") or [])],
        incompatibility_signals=[str(x) for x in (data.get("incompatibility_signals") or [])],
        best_hook_label=str(data.get("best_hook_label") or ""),
        usage=dict(data.get("usage") or {}),
    )


def save_openers(
    extract_dir: Path,
    openers: list[OpenerCandidate],
    recommended_style: str,
    recommended_reason: str,
) -> None:
    _write_json(
        extract_dir,
        "openers.json",
        {
            "openers": [
                {
                    "style": o.style,
                    "text": o.text,
                    "hook_used": o.hook_used,
                    "evidence": o.evidence,
                    "valid": o.valid,
                    "rejection_reason": o.rejection_reason,
                }
                for o in openers
            ],
            "recommended_style": recommended_style,
            "recommended_reason": recommended_reason,
        },
    )


def load_openers(
    extract_dir: Path,
) -> tuple[list[OpenerCandidate], str, str] | None:
    data = _read_json(extract_dir, "openers.json")
    if not data:
        return None
    openers: list[OpenerCandidate] = []
    for item in data.get("openers") or []:
        if not isinstance(item, dict):
            continue
        openers.append(
            OpenerCandidate(
                style=str(item.get("style", "playful")),
                text=str(item.get("text", "")),
                hook_used=str(item.get("hook_used", "")),
                evidence=str(item.get("evidence", "")),
                valid=bool(item.get("valid", True)),
                rejection_reason=str(item.get("rejection_reason", "")),
            )
        )
    return (
        openers,
        str(data.get("recommended_style") or ""),
        str(data.get("recommended_reason") or ""),
    )
