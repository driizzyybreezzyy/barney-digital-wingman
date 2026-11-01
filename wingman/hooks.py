"""Rank conversation hooks by tier (spec section 12)."""

from __future__ import annotations

from wingman.llm import HOOKS_NUM_PREDICT, text_json
from wingman.models import ConversationHook, ProfileAnalysis
from wingman.profile_clean import (
    clean_interest_signals,
    clean_prompts,
    prompt_quality_score,
)


_HOOKS_SYSTEM = """You rank Hinge conversation hooks from profile evidence.

Tier 1 — strong: highly specific, naturally conversational (prompt answers).
Tier 2 — moderate: common interest with personalization potential.
Tier 3 — weak: generic information.
Tier 4 — no useful hook.

Return at most 6 hooks. No duplicates. Each hook must reference a distinct detail.

Respond with ONLY JSON:
{
  "hooks": [
    {"label": "short label", "detail": "specific detail", "tier": 1, "source": "prompt|photo|info"}
  ]
}

Never create hooks from appearance compliments."""


def _norm_key(label: str, detail: str) -> str:
    return f"{label.strip().lower()}|{detail.strip().lower()}"


def _dedupe_hooks(hooks: list[ConversationHook]) -> list[ConversationHook]:
    """Drop duplicate hooks; prefer lowest tier when the same answer appears twice."""
    by_detail: dict[str, ConversationHook] = {}
    for h in hooks:
        detail_key = h.detail.strip().lower()
        label_key = _norm_key(h.label, h.detail)
        existing = by_detail.get(detail_key)
        if existing is None or h.tier < existing.tier:
            by_detail[detail_key] = h
        elif existing and h.tier == existing.tier and len(h.label) < len(existing.label):
            by_detail[detail_key] = h
    seen_label: set[str] = set()
    out: list[ConversationHook] = []
    for h in hooks:
        detail_key = h.detail.strip().lower()
        if by_detail.get(detail_key) is not h:
            continue
        label_key = _norm_key(h.label, h.detail)
        if label_key in seen_label:
            continue
        seen_label.add(label_key)
        out.append(h)
    return out


def _deterministic_hooks(profile: ProfileAnalysis) -> list[ConversationHook]:
    hooks: list[ConversationHook] = []
    for p in clean_prompts(profile):
        answer = p.answer.strip()
        label = p.prompt_text.strip()[:50] or "prompt"
        score = prompt_quality_score(p)
        tier = 1 if score <= 3 else 2 if score <= 5 else 3
        hooks.append(
            ConversationHook(
                label=label,
                detail=answer[:120],
                tier=tier,
                source="prompt",
            )
        )
    for sig in clean_interest_signals(profile)[:4]:
        hooks.append(
            ConversationHook(
                label=sig[:50],
                detail=sig[:120],
                tier=2,
                source="info",
            )
        )
    hooks = _dedupe_hooks(hooks)
    prompt_by_answer = {p.answer.strip(): prompt_quality_score(p) for p in clean_prompts(profile)}
    hooks.sort(key=lambda h: (h.tier, prompt_by_answer.get(h.detail.strip(), 99)))
    return hooks[:6]


def _llm_hooks_low_quality(hooks: list[ConversationHook]) -> bool:
    if not hooks:
        return True
    deduped = _dedupe_hooks(hooks)
    if len(deduped) < len(hooks) - 1:
        return True
    photo_hooks = [h for h in deduped if h.source == "photo"]
    if photo_hooks and len(photo_hooks) >= 2:
        return True
    if len(deduped) <= 2 and all(h.tier >= 2 for h in deduped):
        labels = [h.label.lower() for h in deduped]
        if len(set(labels)) < len(labels):
            return True
    return False


def _deterministic_sufficient(profile: ProfileAnalysis) -> bool:
    """Skip flaky LLM hook ranking when cleaned prompts are already usable."""
    cleaned = clean_prompts(profile)
    if len(cleaned) >= 2:
        return True
    strong = [p for p in cleaned if prompt_quality_score(p) <= 4]
    return len(strong) >= 2


def _compact_evidence(profile: ProfileAnalysis) -> dict:
    prompts = clean_prompts(profile)
    return {
        "name": profile.name,
        "prompts": [{"prompt": p.prompt_text, "answer": p.answer} for p in prompts[:8]],
        "photo_contexts": [
            {"index": p.index, "description": p.description[:120]}
            for p in profile.photo_contexts[:6]
        ],
        "interest_signals": clean_interest_signals(profile)[:6],
        "evidence_bullets": profile.evidence_bullets[:8],
    }


def extract_hooks(profile: ProfileAnalysis) -> list[ConversationHook]:
    deterministic = _deterministic_hooks(profile)
    if _deterministic_sufficient(profile):
        profile.hooks = deterministic
        return deterministic

    evidence = _compact_evidence(profile)
    user = f"Rank conversation hooks:\n{evidence}"
    compact = f"Rank at most 6 distinct hooks. JSON only.\n{evidence}"

    llm_hooks: list[ConversationHook] = []
    usage: dict = {}
    try:
        data, usage = text_json(
            _HOOKS_SYSTEM,
            user,
            num_predict=HOOKS_NUM_PREDICT,
            compact_user=compact,
        )
        for h in (data.get("hooks") or [])[:6]:
            if not isinstance(h, dict):
                continue
            tier = max(1, min(4, int(h.get("tier", 4))))
            llm_hooks.append(
                ConversationHook(
                    label=str(h.get("label", "")),
                    detail=str(h.get("detail", "")),
                    tier=tier,
                    source=str(h.get("source", "")),
                )
            )
        llm_hooks = _dedupe_hooks(llm_hooks)
    except RuntimeError as e:
        print(f"  [hooks] LLM failed ({e}) — using deterministic hooks")

    if _llm_hooks_low_quality(llm_hooks):
        if llm_hooks:
            print("  [hooks] LLM output low quality — using deterministic hooks")
        hooks = deterministic
    else:
        # Merge: prefer LLM ordering but keep deterministic coverage
        by_key = {_norm_key(h.label, h.detail): h for h in deterministic}
        for h in llm_hooks:
            by_key.setdefault(_norm_key(h.label, h.detail), h)
        hooks = _dedupe_hooks(sorted(by_key.values(), key=lambda x: x.tier))[:6]

    if not hooks:
        hooks = deterministic

    profile.hooks = hooks
    profile.usage = _merge_usage(profile.usage, usage)
    return hooks


def _merge_usage(a: dict, b: dict) -> dict:
    return {
        "input_tokens": a.get("input_tokens", 0) + b.get("input_tokens", 0),
        "output_tokens": a.get("output_tokens", 0) + b.get("output_tokens", 0),
    }
