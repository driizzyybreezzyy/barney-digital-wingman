"""Guards for assisted/automated Wingman (daily like cap, Active Now priority)."""

from __future__ import annotations

import config
from wingman.models import CompatibilityResult, ProfileAnalysis
from wingman.profile_clean import profile_is_active_now


class LikeBudget:
    """Tracks likes against free-tier daily cap (resets ~4am local on Hinge)."""

    def __init__(self, max_likes: int | None = None) -> None:
        self.max_likes = int(max_likes if max_likes is not None else config.MAX_LIKES_PER_SESSION)
        self.sent = 0

    def can_send_like(self) -> bool:
        return self.sent < self.max_likes

    def record_like(self) -> None:
        self.sent += 1

    @property
    def exhausted(self) -> bool:
        return self.sent >= self.max_likes

    def remaining(self) -> int:
        return max(0, self.max_likes - self.sent)


def automation_mode() -> bool:
    """True when bot may perform Hinge taps (assisted/automated, not dry_run)."""
    return getattr(config, "RUN_MODE", "dry_run") in ("assisted", "automated")


def should_apply_automation_policy() -> bool:
    """Active Now deferral only for fully automated loop — not human-approved assist."""
    if getattr(config, "DRY_RUN", True):
        return False
    # assisted = you approve each like; never auto-SKIP for Active Now policy
    if getattr(config, "RUN_MODE", "dry_run") == "assisted":
        return False
    if getattr(config, "HUMAN_APPROVAL", True) and getattr(config, "AUTO_ACTION", False):
        return False
    return getattr(config, "RUN_MODE", "dry_run") == "automated"


def would_defer_for_active_now(
    profile: ProfileAnalysis,
    result: CompatibilityResult,
) -> bool:
    """True if live automation would defer this like (inactive profile, not exceptional)."""
    if result.decision != "like" or profile_is_active_now(profile):
        return False
    if not getattr(config, "PREFER_ACTIVE_NOW", True):
        return False
    tier1_hooks = sum(1 for h in profile.hooks if h.tier <= 1)
    if result.confidence_score >= 9 or tier1_hooks >= 3:
        return False
    return True


def apply_active_now_policy(
    profile: ProfileAnalysis,
    result: CompatibilityResult,
) -> CompatibilityResult:
    """Boost Active Now profiles; defer likes on inactive when automating live only."""
    if result.decision != "like":
        return result

    active = profile_is_active_now(profile)
    score = result.confidence_score

    if active:
        score = min(10, score + 2)
        if not any("active now" in w.lower() for w in result.compatibility_signals):
            result.compatibility_signals.append("Active now — higher match probability")
        result.confidence_score = score
        return result

    if not getattr(config, "PREFER_ACTIVE_NOW", True) or not should_apply_automation_policy():
        return result

    # Live automation: save daily likes for Active Now unless profile is exceptional.
    tier1_hooks = sum(1 for h in profile.hooks if h.tier <= 1)
    if score >= 9 or tier1_hooks >= 3:
        result.why.append(
            "(auto-note: not Active Now, but strong enough to like anyway)"
        )
        return result

    result.decision = "skip"
    result.confidence_score = max(result.confidence_score, 5)
    result.why.append(
        "Automation policy: not Active Now — saving daily like for higher match odds"
    )
    result.incompatibility_signals.append("not Active Now (automation defer)")
    return result
