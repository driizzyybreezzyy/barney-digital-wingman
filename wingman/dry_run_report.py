"""Structured dry-run report — no Hinge decision actions."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from wingman.models import WingmanRecommendation
from wingman.opener import GENERIC_PATTERNS, validate_opener
from wingman.automation_guard import would_defer_for_active_now


def _is_generic_opener(text: str) -> bool:
    lower = text.lower().strip()
    if not lower:
        return True
    for pat in GENERIC_PATTERNS:
        if re.search(pat, lower):
            return True
    return False


def _appearance_only_why(rec: WingmanRecommendation) -> bool:
    appearance = ("attractive", "beautiful", "pretty", "gorgeous", "hot ", "looks amazing")
    why = " ".join(rec.compatibility.why).lower()
    hookish = any(k in why for k in ("prompt", "hook", "effort", "compat", "active now"))
    return any(p in why for p in appearance) and not hookish


def _hook_frames_from_merged(merged: dict[str, Any] | None, detail: str) -> list[int]:
    if not merged:
        return []
    detail_l = detail.lower()
    frames: list[int] = []
    for item in merged.get("prompts") or []:
        q = str(item.get("prompt_text", "")).lower()
        a = str(item.get("answer", "")).lower()
        if detail_l in q or detail_l in a:
            frames.extend(item.get("source_frames") or [])
    return sorted(set(frames))


def assess_proposed_action(
    rec: WingmanRecommendation,
    opener_text: str,
    opener_style: str,
    hook_used: str,
) -> tuple[str, str]:
    """Return (effective_action, reason) for dry-run — may downgrade LIKE to SKIP."""
    if rec.compatibility.decision != "like":
        return "SKIP", "compatibility decision is skip"

    if not opener_text:
        return "SKIP", "no valid opener — do not invent a weak comment"

    hook = next(
        (h for h in rec.profile.hooks if h.label == hook_used or h.detail in opener_text),
        None,
    )
    if hook:
        valid, reason = validate_opener(opener_text, _hook_context_from_rec(hook))
        if not valid:
            return "SKIP", f"opener invalid: {reason}"
    elif _is_generic_opener(opener_text):
        return "SKIP", "opener failed quality check (generic template)"

    if _is_generic_opener(opener_text):
        return "SKIP", "opener is generic — would not send"

    return "LIKE", "valid personalized opener on detected hook"


def _hook_context_from_rec(hook):
    from wingman.opener import HookContext, _anchor_words, _hook_key

    return HookContext(
        label=hook.label,
        detail=hook.detail,
        evidence=hook.detail,
        priority=hook.tier,
        anchor_words=_anchor_words(hook.label, hook.detail),
        hook_key=_hook_key(hook.label, hook.detail),
    )


def build_report(
    rec: WingmanRecommendation,
    *,
    opener_text: str,
    opener_style: str,
    hook_used: str,
    frames_dir: Path,
    frame_count: int,
    merged: dict[str, Any] | None = None,
) -> dict[str, Any]:
    effective, eff_reason = assess_proposed_action(rec, opener_text, opener_style, hook_used)
    p = rec.profile
    c = rec.compatibility

    top_hooks = []
    for h in (p.hooks or [])[:3]:
        top_hooks.append({
            "label": h.label,
            "detail": h.detail,
            "tier": h.tier,
            "source": h.source,
            "source_frames": _hook_frames_from_merged(merged, h.detail),
        })

    personalized = bool(opener_text) and not _is_generic_opener(opener_text)
    generic = _is_generic_opener(opener_text) if opener_text else True
    hey = bool(re.match(r"^\s*(hey|hi|hello)\b", opener_text, re.I)) if opener_text else False

    automation_note = None
    if c.decision == "like" and would_defer_for_active_now(p, c):
        automation_note = (
            "Live automation would defer this like (not Active Now). "
            "Human judgment / dry-run keeps LIKE."
        )

    return {
        "profile": {
            "name": p.name,
            "age": p.age,
            "location": p.location,
            "frame_count": frame_count,
            "profile_effort": p.profile_effort,
            "frames_dir": str(frames_dir),
        },
        "decision": {
            "raw": c.decision.upper(),
            "effective": effective,
            "effective_reason": eff_reason,
            "score": c.confidence_score,
            "why": c.why,
            "compatibility_signals": c.compatibility_signals,
            "incompatibility_signals": c.incompatibility_signals,
            "automation_note": automation_note,
        },
        "hooks": top_hooks,
        "opener": {
            "proposed_comment": opener_text or "(none)",
            "style": opener_style or "(none)",
            "hook_used": hook_used or "(none)",
            "valid": bool(opener_text) and effective == "LIKE",
        },
        "quality": {
            "personalized": personalized,
            "appearance_only_reasoning": _appearance_only_why(rec),
            "generic": generic,
            "starts_with_hey_hi_hello": hey,
        },
        "action": "DRY RUN — NO HINGE LIKE/SKIP/COMMENT",
        "capture_note": (
            "Profile scroll + screenshots used for analysis only; "
            "no heart/skip/send-like taps."
        ),
    }


def print_dry_run_report(report: dict[str, Any]) -> None:
    p = report["profile"]
    d = report["decision"]
    print("\n" + "═" * 44)
    print("DRY-RUN VALIDATION REPORT")
    print("═" * 44)

    print("\nPROFILE:")
    print(f"  name:     {p['name']}")
    print(f"  age:      {p['age']}")
    print(f"  location: {p['location'] or '(not extracted)'}")
    print(f"  frames:   {p['frame_count']} analyzed")
    print(f"  saved:    {p['frames_dir']}")

    print("\nDECISION:")
    print(f"  raw:       {d['raw']}")
    print(f"  effective: {d['effective']}  ({d['effective_reason']})")
    print(f"  score:     {d['score']}/10")
    print("  reasons:")
    for w in d["why"] or ["(none)"]:
        print(f"    • {w}")
    if d.get("automation_note"):
        print(f"  automation: {d['automation_note']}")

    print("\nHOOKS (top 3):")
    for h in report["hooks"] or [{"label": "(none)", "detail": "", "source_frames": []}]:
        frames = h.get("source_frames") or []
        frame_note = f"frames {frames}" if frames else "source frame unknown"
        print(f"  • [{h.get('label', '?')}] {h.get('detail', '')}")
        print(f"    source: {h.get('source', '?')} | {frame_note}")

    o = report["opener"]
    q = report["quality"]
    print("\nOPENER:")
    print(f"  proposed:  {o['proposed_comment']}")
    print(f"  style:     {o['style']}")
    print(f"  hook used: {o['hook_used']}")

    print("\nQUALITY:")
    print(f"  personalized:        {'yes' if q['personalized'] else 'no'}")
    print(f"  appearance-only:     {'yes' if q['appearance_only_reasoning'] else 'no'}")
    print(f"  generic:             {'yes' if q['generic'] else 'no'}")
    print(f"  starts Hey/Hi/Hello: {'yes' if q['starts_with_hey_hi_hello'] else 'no'}")

    print("\nACTION:")
    print(f"  {report['action']}")
    print(f"  ({report['capture_note']})")
    print("═" * 44 + "\n")


def save_dry_run_report(report: dict[str, Any], extract_dir: Path) -> Path:
    extract_dir.mkdir(parents=True, exist_ok=True)
    path = extract_dir / "dry_run_result.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path
