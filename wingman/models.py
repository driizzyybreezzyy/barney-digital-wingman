"""Structured types for the Wingman pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PromptItem:
    prompt_text: str = ""
    answer: str = ""
    readable: bool = True


@dataclass
class PhotoContext:
    index: int = 1
    description: str = ""


@dataclass
class ConversationHook:
    label: str
    detail: str
    tier: int  # 1=strong, 2=moderate, 3=weak, 4=none
    source: str = ""  # prompt | photo | info


@dataclass
class ProfileAnalysis:
    platform: str = "generic"
    name: str = "unknown"
    age: int | None = None
    location: str = ""
    basic_info: str = ""
    prompts: list[PromptItem] = field(default_factory=list)
    photo_contexts: list[PhotoContext] = field(default_factory=list)
    interest_signals: list[str] = field(default_factory=list)
    profile_effort: str = "unknown"  # low | medium | high | unknown
    evidence_bullets: list[str] = field(default_factory=list)
    hooks: list[ConversationHook] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    frame_count: int = 1
    summary: str = ""
    desirability_score: int = 5
    league_signals: list[str] = field(default_factory=list)

    def best_hook(self) -> ConversationHook | None:
        from wingman.profile_clean import clean_prompts

        cleaned = clean_prompts(self)
        if cleaned:
            top_answer = cleaned[0].answer.strip().lower()
            for h in sorted(self.hooks, key=lambda x: (x.tier, x.detail)):
                d = h.detail.strip().lower()
                if d == top_answer or top_answer in d or d in top_answer:
                    return h
        ranked = sorted(self.hooks, key=lambda h: h.tier)
        for h in ranked:
            if h.tier <= 2 and h.detail.strip():
                return h
        return ranked[0] if ranked else None


@dataclass
class OpenerCandidate:
    style: str  # playful | clever | flirty
    text: str
    hook_used: str
    evidence: str
    valid: bool = True
    rejection_reason: str = ""


@dataclass
class CompatibilityResult:
    decision: str  # like | skip
    confidence_score: int  # 1-10
    why: list[str] = field(default_factory=list)
    compatibility_signals: list[str] = field(default_factory=list)
    incompatibility_signals: list[str] = field(default_factory=list)
    best_hook_label: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
    reciprocity_probability: str = "Medium"  # Low, Medium, High


@dataclass
class WingmanRecommendation:
    profile: ProfileAnalysis
    compatibility: CompatibilityResult
    openers: list[OpenerCandidate] = field(default_factory=list)
    recommended_style: str = ""
    recommended_reason: str = ""
    total_usage: dict[str, Any] = field(default_factory=dict)
