"""Execute Wingman LIKE/SKIP on Hinge after pipeline judgment."""

from __future__ import annotations

from wingman.automation_guard import LikeBudget
from wingman.feedback import record_feedback
from wingman.models import WingmanRecommendation

import config


def pick_opener_text(rec: WingmanRecommendation) -> tuple[str, str]:
    """Return (opener_text, style) — prefer playful, then recommended, then any valid."""
    if not rec.openers:
        return "", ""

    valid = [o for o in rec.openers if o.valid]
    if not valid:
        return "", ""

    for prefer in (rec.recommended_style, "playful", "clever", "flirty"):
        if not prefer:
            continue
        for o in valid:
            if o.style == prefer:
                return o.text, o.style

    o = valid[0]
    return o.text, o.style


def _should_auto_like(rec: WingmanRecommendation) -> tuple[bool, str]:
    """Extra gates before spending a daily like in automation."""
    from wingman.profile_clean import clean_prompts, profile_is_active_now

    if rec.compatibility.decision != "like":
        return False, "decision is skip"

    if not getattr(config, "AUTOMATE_REQUIRE_ACTIVE_NOW", True):
        return True, ""

    prompts = clean_prompts(rec.profile)
    active = profile_is_active_now(rec.profile)
    if len(prompts) >= 2:
        return True, ""
    if active:
        return True, ""
    return False, "thin profile (1 prompt) and not Active now — saving like"


def execute_on_hinge(
    rec: WingmanRecommendation,
    *,
    profile_id: str,
    budget: LikeBudget,
    frames_dir: str = "",
    dry_run: bool = False,
) -> dict:
    """Perform skip or like+comment on the current Discover profile.

    When dry_run=True, prints intended action without tapping Hinge.
    """
    decision = rec.compatibility.decision
    name = rec.profile.name
    
    base_extra = {
        "desirability_score": getattr(rec.profile, "desirability_score", 5),
        "reciprocity_probability": getattr(rec.compatibility, "reciprocity_probability", "Medium")
    }

    def _skip_action(reason: str, user_action: str) -> dict:
        msg = f"[auto{'-dry' if dry_run else ''}] SKIP {name!r} — {reason}"
        print(msg)
        if not dry_run:
            from main import do_skip

            do_skip()
        record_feedback(
            profile_id=profile_id,
            ai_decision=decision,
            decision_reason="; ".join(rec.compatibility.why),
            best_hook=rec.compatibility.best_hook_label,
            opener_style="",
            opener_generated="",
            opener_used="",
            aryan_approved=True,
            aryan_edited=False,
            user_action=user_action,
            like_sent=False,
            extra={"frames_dir": frames_dir, "automated": True, "dry_run": dry_run, **base_extra},
        )
        return {"action": "skip", "like_sent": False, "reason": reason}

    if decision != "like":
        return _skip_action("compatibility skip", "auto_skip" if not dry_run else "auto_skip_dry")

    ok, gate_reason = _should_auto_like(rec)
    if not ok:
        return _skip_action(gate_reason, "auto_skip_policy")

    if not budget.can_send_like():
        print(
            f"[auto{'-dry' if dry_run else ''}] Daily like cap reached ({budget.max_likes}). Stopping."
        )
        return {"action": "cap_reached", "like_sent": False}

    opener_text, opener_style = pick_opener_text(rec)
    if not opener_text:
        return _skip_action("no valid opener", "auto_skip_no_opener")

    print(f"[auto{'-dry' if dry_run else ''}] LIKE {name!r} + comment ({opener_style})")
    print(f"  → {opener_text}")
    if not dry_run:
        from main import do_like

        do_like(opener_text)
    budget.record_like()

    generated = next((o.text for o in rec.openers if o.style == opener_style), opener_text)
    record_feedback(
        profile_id=profile_id,
        ai_decision=decision,
        decision_reason="; ".join(rec.compatibility.why),
        best_hook=rec.compatibility.best_hook_label,
        opener_style=opener_style,
        opener_generated=generated,
        opener_used=opener_text,
        aryan_approved=True,
        aryan_edited=opener_text != generated,
        user_action="auto_like" if not dry_run else "auto_like_dry",
        like_sent=True,
        extra={
            "frames_dir": frames_dir,
            "automated": True,
            "dry_run": dry_run,
            "likes_remaining": budget.remaining(),
            **base_extra
        },
    )
    return {
        "action": "like",
        "like_sent": True,
        "opener": opener_text,
        "likes_remaining": budget.remaining(),
        "dry_run": dry_run,
    }
