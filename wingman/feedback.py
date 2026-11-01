"""Record approval, edit, and reject feedback."""

from __future__ import annotations

from typing import Any

from wingman.experiment import append_wingman_record


def record_feedback(
    *,
    profile_id: str,
    ai_decision: str,
    decision_reason: str,
    best_hook: str,
    opener_style: str,
    opener_generated: str,
    opener_used: str,
    aryan_approved: bool,
    aryan_edited: bool,
    user_action: str,
    like_sent: bool = False,
    extra: dict[str, Any] | None = None,
) -> None:
    record: dict[str, Any] = {
        "experiment_id": "wingman",
        "profile_id": profile_id,
        "ai_decision": ai_decision,
        "decision_reason": decision_reason,
        "best_hook": best_hook,
        "opener_style": opener_style,
        "opener_generated": opener_generated,
        "opener_used": opener_used,
        "aryan_approved": aryan_approved,
        "aryan_edited": aryan_edited,
        "user_action": user_action,
        "like_sent": like_sent,
        "matched": None,
        "replied": None,
        "conversation_quality": None,
        "date": None,
    }
    if extra:
        record.update(extra)
    append_wingman_record(record)
