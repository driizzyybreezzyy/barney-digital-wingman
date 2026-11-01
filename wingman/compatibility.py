"""Stage 2: compatibility decision — not appearance-based."""

from __future__ import annotations

import config
from wingman.llm import COMPAT_NUM_PREDICT, text_json
from wingman.models import CompatibilityResult, ProfileAnalysis
from wingman.personality import load_aryan_profile, personality_prompt_section
from wingman.profile_clean import clean_prompts, profile_is_active_now, prompt_quality_score
from wingman.automation_guard import apply_active_now_policy


_COMPAT_SYSTEM = """You are Digital Wingman deciding LIKE or SKIP for Aryan.

CRITICAL: Do NOT recommend LIKE primarily because of attractiveness or photo appeal.
Base the decision on profile effort, prompts, interests, compatibility, and conversation
hooks. Photo context is for activity/setting only.

GALE-SHAPLEY OPTIMIZATION: Hinge penalizes one-sided preferences. Compare the profile's desirability 
against Aryan's baseline. If the profile's league is significantly higher, reciprocity probability is Low. 
If it's Low, lean towards SKIP to protect Aryan's priority score, unless compatibility hooks are exceptionally strong.

Respond with ONLY JSON:
{
  "decision": "like|skip",
  "confidence_score": 1-10,
  "why": ["reason 1", "reason 2"],
  "compatibility_signals": ["..."],
  "incompatibility_signals": ["..."],
  "best_hook_label": "label of strongest hook or empty",
  "reciprocity_probability": "Low|Medium|High"
}

If only appearance stands out with no hooks, decision MUST be skip.
If profile_effort is low and no readable prompts, lean skip."""


def evaluate_compatibility(
    profile: ProfileAnalysis,
    *,
    aryan_hinge_context: str | None = None,
) -> CompatibilityResult:
    aryan = load_aryan_profile()
    age_range = aryan.get("identity", {}).get("preferred_age_range", [18, 24])
    hooks_summary = [
        {"label": h.label, "detail": h.detail, "tier": h.tier}
        for h in profile.hooks
    ]
    user = _build_compat_user(profile, hooks_summary, age_range, aryan_hinge_context)

    system = (
        _COMPAT_SYSTEM
        + "\n\n"
        + personality_prompt_section()
        + "\n\nConsider fit between the user's own dating profile (if provided) and this profile."
        + "\n\n## Rubric\n"
        + config.PREFERENCES.strip()
    )
    compact_system = _COMPAT_SYSTEM + "\n\n## Rubric\n" + config.PREFERENCES.strip()[:800]

    try:
        data, usage = text_json(
            system,
            str(user),
            num_predict=COMPAT_NUM_PREDICT,
            compact_user=str(_compact_compat_user(profile, hooks_summary, aryan_hinge_context)),
        )
    except RuntimeError as e:
        print(f"  [compat] LLM failed ({e}) — rule-based fallback")
        return finalize_compatibility(
            profile, _rule_based_compat(profile, hooks_summary, age_range, usage={})
        )

    if _is_empty_compat_response(data, usage):
        print("  [compat] LLM returned empty/thin JSON — retrying compact")
        try:
            data, usage = text_json(
                compact_system,
                str(_compact_compat_user(profile, hooks_summary, aryan_hinge_context)),
                num_predict=COMPAT_NUM_PREDICT,
                compact_user=str(_compact_compat_user(profile, hooks_summary, aryan_hinge_context)),
            )
        except RuntimeError as e:
            print(f"  [compat] compact retry failed ({e}) — rule-based fallback")
            return finalize_compatibility(
            profile, _rule_based_compat(profile, hooks_summary, age_range, usage={})
        )

    if _is_empty_compat_response(data, usage):
        print("  [compat] LLM still empty — rule-based fallback")
        return finalize_compatibility(
            profile, _rule_based_compat(profile, hooks_summary, age_range, usage=usage)
        )

    decision = str(data.get("decision", "skip")).lower()
    if decision not in ("like", "skip"):
        decision = "skip"
    score = int(data.get("confidence_score", 3))
    score = max(1, min(10, score))

    why = [str(x) for x in (data.get("why") or [])]
    _reject_appearance_only(decision, why)
    why = sanitize_compat_why(profile, why)

    if _llm_skip_contradicts_profile(decision, why, profile, hooks_summary):
        print("  [compat] LLM skip contradicts cleaned profile — rule-based override")
        return finalize_compatibility(
            profile,
            _rule_based_compat(profile, hooks_summary, age_range, usage=usage),
        )

    result = CompatibilityResult(
        decision=decision,
        confidence_score=score,
        why=why,
        compatibility_signals=[str(x) for x in (data.get("compatibility_signals") or [])],
        incompatibility_signals=[str(x) for x in (data.get("incompatibility_signals") or [])],
        best_hook_label=str(data.get("best_hook_label") or ""),
        usage=usage,
        reciprocity_probability=str(data.get("reciprocity_probability") or "Medium"),
    )
    return finalize_compatibility(profile, result)


def _build_compat_user(
    profile: ProfileAnalysis,
    hooks_summary: list[dict],
    age_range: list,
    aryan_hinge_context: str | None,
) -> dict:
    prompts = clean_prompts(profile)
    return {
        "aryan_desirability_baseline": 6,  # Default baseline for reciprocity matching
        "age_gate": f"{config.AGE_MIN}-{config.AGE_MAX}",
        "preferred_age_range": age_range,
        "aryan_live_hinge_profile": (aryan_hinge_context or "(not scanned)")[:600],
        "profile": {
            "name": profile.name,
            "age": profile.age,
            "location": profile.location,
            "profile_effort": profile.profile_effort,
            "desirability_score": getattr(profile, "desirability_score", 5),
            "league_signals": getattr(profile, "league_signals", []),
            "summary": profile.summary,
            "prompts": [{"q": p.prompt_text, "a": p.answer} for p in prompts[:8]],
            "hooks": hooks_summary[:6],
        },
    }


def _is_empty_compat_response(data: dict, usage: dict) -> bool:
    out_tokens = usage.get("output_tokens", 0)
    why = data.get("why") or []
    has_decision = str(data.get("decision", "")).lower() in ("like", "skip")
    if out_tokens < 20:
        return True
    if has_decision and not why and not data.get("compatibility_signals"):
        if out_tokens < 80:
            return True
    return False


def _rule_based_compat(
    profile: ProfileAnalysis,
    hooks_summary: list[dict],
    age_range: list,
    *,
    usage: dict,
) -> CompatibilityResult:
    """Explicit fallback when LLM fails — uses merged profile facts only."""
    prompts = clean_prompts(profile)
    why: list[str] = []
    compat_signals: list[str] = []
    incompat_signals: list[str] = []

    age_ok = True
    if profile.age is not None:
        lo, hi = age_range[0], age_range[-1]
        if config.AGE_MIN is not None and profile.age < config.AGE_MIN:
            age_ok = False
            incompat_signals.append(f"age {profile.age} below gate {config.AGE_MIN}")
        if config.AGE_MAX is not None and profile.age > config.AGE_MAX:
            age_ok = False
            incompat_signals.append(f"age {profile.age} above gate {config.AGE_MAX}")
        if profile.age < lo or profile.age > hi:
            incompat_signals.append(f"age {profile.age} outside preferred {lo}-{hi}")
        else:
            compat_signals.append(f"age {profile.age} in preferred range")

    tier1 = [h for h in hooks_summary if int(h.get("tier", 4)) <= 1]
    effort = profile.profile_effort.lower()
    rich_profile = effort in ("high", "medium") and len(prompts) >= 2

    if rich_profile:
        compat_signals.append(f"profile effort {profile.profile_effort}, {len(prompts)} usable prompts")
    if tier1:
        compat_signals.append(f"{len(tier1)} strong hook(s): {tier1[0].get('label', '')}")

    best_hook = tier1[0]["label"] if tier1 else (hooks_summary[0]["label"] if hooks_summary else "")

    if not age_ok:
        decision = "skip"
        confidence = 7
        why.append("Age outside configured gate — conservative skip")
    elif rich_profile and tier1 and age_ok:
        decision = "like"
        confidence = 7
        why.append("Rule fallback: rich profile with specific prompt hooks and age in range")
        why.append(f"Strongest hook: {best_hook}")
    elif rich_profile and age_ok:
        decision = "like"
        confidence = 6
        why.append("Rule fallback: usable prompts and age in range, moderate hooks")
    else:
        decision = "skip"
        confidence = 5
        why.append("Rule fallback: insufficient prompt depth or hooks for confident like")

    return finalize_compatibility(
        profile,
        CompatibilityResult(
            decision=decision,
            confidence_score=confidence,
            why=why,
            compatibility_signals=compat_signals,
            incompatibility_signals=incompat_signals,
            best_hook_label=best_hook,
            usage=usage,
            reciprocity_probability="Medium",
        ),
    )


def finalize_compatibility(
    profile: ProfileAnalysis,
    result: CompatibilityResult,
) -> CompatibilityResult:
    """Sanitize LLM reasons and apply Active Now policy (live automation only)."""
    result.why = sanitize_compat_why(profile, result.why)
    result.compatibility_signals = sanitize_compat_signals(profile, result.compatibility_signals)
    if profile_is_active_now(profile):
        if not any("active now" in s.lower() for s in result.compatibility_signals):
            result.compatibility_signals.append("Active now on Hinge")
    if not result.best_hook_label.strip():
        best = profile.best_hook()
        if best:
            result.best_hook_label = best.label
    return apply_active_now_policy(profile, result)


_UNGROUNDED_WHY_CHECKS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("mountain", ("mountain", "mountains", "mountainous")),
    ("landscape", ("landscape",)),
    ("hiking", ("hik", "trail")),
    ("beach", ("beach", "ocean", "sea")),
    ("minion", ("bob", "kevin", "stuart", "minion")),
    ("pythagorean", ("pythagorean", "theorem")),
    ("greek", ("greek", "philosopher", "diss track")),
    ("yap", ("yap", "yapping", "nerdy")),
    ("perfume", ("perfume",)),
    ("stoic", ("stoic",)),
    ("nbhd", ("nbhd", "neighbourhood", "neighborhood")),
)


def _profile_evidence_blob(profile: ProfileAnalysis) -> str:
    prompts = clean_prompts(profile)
    parts = [f"{p.prompt_text} {p.answer}" for p in prompts]
    parts.extend(profile.interest_signals[:8])
    parts.extend(h.detail for h in profile.hooks[:8])
    parts.append(profile.summary or "")
    return " ".join(parts).lower()


def sanitize_compat_why(profile: ProfileAnalysis, why: list[str]) -> list[str]:
    """Drop compatibility reasons that cite details absent from cleaned profile evidence."""
    blob = _profile_evidence_blob(profile)
    cleaned: list[str] = []
    for reason in why:
        rl = reason.lower()
        if "automation policy" in rl or "(auto-note" in rl:
            cleaned.append(reason)
            continue
        drop = False
        for keyword, required_any in _UNGROUNDED_WHY_CHECKS:
            if keyword in rl and not any(token in blob for token in required_any):
                drop = True
                break
        if not drop:
            cleaned.append(reason)
    return cleaned or why


def sanitize_compat_signals(profile: ProfileAnalysis, signals: list[str]) -> list[str]:
    """Drop hallucinated compatibility signals not grounded in profile."""
    blob = _profile_evidence_blob(profile)
    cleaned: list[str] = []
    for sig in signals:
        sl = sig.lower()
        drop = False
        for keyword, required_any in _UNGROUNDED_WHY_CHECKS:
            if keyword in sl and not any(token in blob for token in required_any):
                drop = True
                break
        if not drop:
            cleaned.append(sig)
    return cleaned


_APPEARANCE_PHRASES = (
    "visually appealing",
    "attractive photo",
    "looks attractive",
    "beautiful photo",
    "pretty",
    "hot ",
    "gorgeous",
    "looks amazing",
)


def _llm_skip_contradicts_profile(
    decision: str,
    why: list[str],
    profile: ProfileAnalysis,
    hooks_summary: list[dict],
) -> bool:
    """Detect false-negative SKIP when merge/cleaning shows a rich prompt profile."""
    if decision != "skip":
        return False
    why_text = " ".join(why).lower()
    suspicious = (
        "profile effort is low" in why_text
        or "no usable conversation hook" in why_text
        or "no usable hook" in why_text
    )
    if not suspicious:
        return False
    prompts = clean_prompts(profile)
    effort = profile.profile_effort.lower()
    tier1 = [h for h in hooks_summary if int(h.get("tier", 4)) <= 1]
    strong = [p for p in prompts if prompt_quality_score(p) <= 4]
    return effort in ("high", "medium") and len(prompts) >= 2 and (len(tier1) >= 1 or len(strong) >= 2)


def _reject_appearance_only(decision: str, why: list[str]) -> None:
    if decision != "like" or not why:
        return
    text = " ".join(why).lower()
    appearance_hits = sum(1 for p in _APPEARANCE_PHRASES if p in text)
    hook_hits = sum(
        1 for w in why
        if any(k in w.lower() for k in ("prompt", "hook", "interest", "effort", "compat"))
    )
    if appearance_hits >= 1 and hook_hits == 0:
        why.append("(auto-note: appearance-only reasoning flagged — verify hooks manually)")


def _compact_compat_user(
    profile: ProfileAnalysis,
    hooks_summary: list[dict],
    aryan_hinge_context: str | None,
) -> dict:
    prompts = clean_prompts(profile)
    return {
        "profile": {
            "name": profile.name,
            "age": profile.age,
            "location": profile.location,
            "profile_effort": profile.profile_effort,
            "prompts": [{"q": p.prompt_text, "a": p.answer} for p in prompts[:5]],
            "hooks": hooks_summary[:4],
        },
        "aryan_live_hinge_profile": (aryan_hinge_context or "")[:400],
    }
