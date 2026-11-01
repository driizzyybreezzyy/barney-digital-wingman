"""Print Wingman recommendation and collect human approval (dry-run safe)."""

from __future__ import annotations

import config
from wingman.automation_guard import would_defer_for_active_now
from wingman.feedback import record_feedback
from wingman.models import OpenerCandidate, WingmanRecommendation
from wingman.profile_clean import clean_prompts, profile_is_active_now


def pick_recommended_opener(rec: WingmanRecommendation) -> OpenerCandidate | None:
    """Valid opener on the strongest hook — not first in list."""
    from wingman.opener import _pick_recommended_opener

    if not rec.openers:
        return None
    style, _ = _pick_recommended_opener(rec.openers, rec.profile)
    if style:
        for o in rec.openers:
            if o.style == style and o.valid:
                return o
    for o in rec.openers:
        if o.valid:
            return o
    return None


def print_production_preflight(*, assist_send: bool = False) -> None:
    """Checklist before a full IRL pipeline test."""
    print("═" * 44)
    print("PRODUCTION TEST — FULL PIPELINE")
    print("═" * 44)
    print("  Phone: Hinge open on Discover (one profile visible)")
    print("  Phone: dismiss notification shade BEFORE starting")
    print("  Bot:   scroll + screenshots only (~15–25 min)")
    if assist_send:
        print("  After you approve (1/2/3/e): bot taps heart + types comment")
        print("  Language: English / Hindi / Gujarati — matched to the hook")
        print("  First time on this phone? Run: .venv/bin/python calibrate.py")
    else:
        print("  You:   send heart + comment manually after approval")
    print("  Log:   wingman> 1/2/3 | e edit | s skip")
    print("  Safety: no taps during scroll; like/skip only after approval")
    print("═" * 44 + "\n")


def print_production_action(rec: WingmanRecommendation) -> None:
    """Copy-paste card for IRL: decision → hook → comment → phone steps."""
    c = rec.compatibility
    best = rec.profile.best_hook()
    hook_detail = best.detail if best else c.best_hook_label or "(none)"
    opener = pick_recommended_opener(rec)

    print("\n" + "═" * 44)
    print("PRODUCTION — YOUR MOVE ON PHONE")
    print("═" * 44)
    print(f"  Decision:  {c.decision.upper()} ({c.confidence_score}/10)")
    if profile_is_active_now(rec.profile):
        print("  Active now: yes")
    print(f"  Hook:      {hook_detail}")

    if c.decision == "like" and opener:
        print(f"  Send as:   {opener.style.capitalize()} (pick 1/2/3 or e to edit in your voice)")
        print(f"  Suggested: {opener.text}")
        print("\n  Steps:")
        print("    1. Read hooks above — pick what YOU would actually say")
        print("    2. Tap heart + comment on Hinge")
        print("    3. Paste or write your version")
        print("    4. Send like")
        if getattr(config, "RUN_MODE", "dry_run") == "dry_run":
            print("    5. Log here: wingman> 1/2/3 or e edit, s skip")
    elif c.decision == "like":
        print("  Comment:   (no valid opener — craft manually or skip)")
        print("\n  Steps:")
        print("    1. Skip, or like with your own comment")
        print("    2. Log: wingman> s or e")
    else:
        print("  Comment:   (none — SKIP)")
        print("\n  Steps:")
        print("    1. Skip on Hinge")
        print("    2. Log: wingman> s")

    if c.decision == "like" and would_defer_for_active_now(rec.profile, c):
        print(
            "\n  Note: Live bot would defer (not Active Now). "
            "You can still like manually."
        )
    print("═" * 44)


def _bar() -> None:
    print("━" * 22)


def print_recommendation(rec: WingmanRecommendation) -> None:
    p = rec.profile
    c = rec.compatibility
    _bar()
    print("DIGITAL WINGMAN")
    _bar()
    print("\nPROFILE ANALYSIS")
    print(f"Name: {p.name}")
    if p.frame_count > 1:
        print(f"Frames analyzed: {p.frame_count} (full scroll)")
    if p.summary:
        print(f"Summary: {p.summary}")
    if p.age is not None:
        print(f"Age: {p.age}")
    if p.location:
        print(f"Location: {p.location}")
    if p.basic_info:
        print(f"Info: {p.basic_info}")
    if profile_is_active_now(p):
        print("Active now: yes (prioritize for likes when automating)")
    print(f"Profile effort: {p.profile_effort}")
    print("\nEvidence:")
    cleaned = clean_prompts(p)
    if cleaned:
        for pr in cleaned[:8]:
            print(f"  • Prompt: {pr.prompt_text}")
            print(f"    Answer: {pr.answer}")
    elif p.evidence_bullets:
        for bullet in p.evidence_bullets[:12]:
            print(f"  • {bullet}")
    else:
        print("  • (none extracted)")
    for ph in p.photo_contexts[:6]:
        if ph.description:
            print(f"  • Photo {ph.index}: {ph.description}")
    if p.interest_signals:
        print(f"  • Interests: {', '.join(p.interest_signals)}")
    if p.hooks:
        print("\nConversation hooks:")
        for h in p.hooks:
            print(f"  • Tier {h.tier} [{h.label}]: {h.detail}")

    print("\nCOMPATIBILITY")
    print(f"Decision: {c.decision.upper()}")
    print(f"Confidence: {c.confidence_score}/10")
    print("\nWhy:")
    for w in c.why or ["(no reasons provided)"]:
        print(f"  • {w}")
    if c.compatibility_signals:
        print("\nCompatibility signals:")
        for s in c.compatibility_signals:
            print(f"  + {s}")
    if c.incompatibility_signals:
        print("\nIncompatibility signals:")
        for s in c.incompatibility_signals:
            print(f"  - {s}")

    best = rec.profile.best_hook()
    if best:
        print(f"\nBEST HOOK:\n{best.detail}  ({best.label})")
    else:
        print(f"\nBEST HOOK:\n{c.best_hook_label or '(none)'}")

    if rec.openers:
        print("\nOPENERS:")
        for i, o in enumerate(rec.openers, 1):
            flag = "" if o.valid else f" [INVALID: {o.rejection_reason}]"
            print(f"  [{i}] {o.style.capitalize()}: {o.text}{flag}")
            print(f"      Hook used: {o.hook_used}")
            print(f"      Evidence: {o.evidence}")
        if rec.recommended_style:
            print(f"\nRecommended: #{_style_index(rec.openers, rec.recommended_style)} "
                  f"{rec.recommended_style.capitalize()}")
            if rec.recommended_reason:
                print(f"Reason: {rec.recommended_reason}")

    mode = getattr(config, "RUN_MODE", "dry_run")
    print(f"\n[RUN_MODE={mode}] ", end="")
    if mode == "dry_run":
        print("No Hinge action will be taken.")
    print_production_action(rec)
    _bar()


def _style_index(openers: list[OpenerCandidate], style: str) -> int:
    for i, o in enumerate(openers, 1):
        if o.style == style:
            return i
    return 1


def hinge_actions_allowed() -> bool:
    """True only when explicitly configured for assisted automation."""
    if getattr(config, "RUN_MODE", "dry_run") != "assisted":
        return False
    if not getattr(config, "AUTO_ACTION", False):
        return False
    return True


def run_approval(
    rec: WingmanRecommendation,
    profile_id: str,
    *,
    assist_send: bool = False,
    frames_dir: str = "",
) -> dict:
    """Interactive approval loop. Sends on Hinge when assist_send=True."""
    print_recommendation(rec)
    
    base_extra = {
        "desirability_score": getattr(rec.profile, "desirability_score", 5),
        "reciprocity_probability": getattr(rec.compatibility, "reciprocity_probability", "Medium")
    }

    if not getattr(config, "HUMAN_APPROVAL", True):
        raise RuntimeError("HUMAN_APPROVAL must be True for Wingman sessions")

    if assist_send:
        print("\nCommands:")
        print("  1/2/3  pick opener and send on Hinge")
        print("  l      like anyway (generate openers if SKIP)")
        print("  c      your custom comment → bot sends")
        print("  e      edit an opener | s skip | r regenerate | q quit")
        print("[assist-send] After approve, bot taps heart + types comment.")
    elif getattr(config, "RUN_MODE", "dry_run") == "dry_run":
        print("\nCommands: 1/2/3 pick opener | e edit | s skip | r regenerate | q quit")
        print("[dry_run] Approve logs your choice only — you send manually on phone.")
    else:
        print("\nCommands: 1/2/3 | e | s | r | q")

    while True:
        try:
            cmd = input("\nwingman> ").strip().lower()
        except EOFError:
            cmd = "q"

        if cmd in ("q", "quit", "exit"):
            record_feedback(
                profile_id=profile_id,
                ai_decision=rec.compatibility.decision,
                decision_reason="; ".join(rec.compatibility.why),
                best_hook=rec.compatibility.best_hook_label,
                opener_style="",
                opener_generated="",
                opener_used="",
                aryan_approved=False,
                aryan_edited=False,
                user_action="quit",
                extra=base_extra,
            )
            return {"action": "quit"}

        if cmd in ("s", "skip"):
            record_feedback(
                profile_id=profile_id,
                ai_decision=rec.compatibility.decision,
                decision_reason="; ".join(rec.compatibility.why),
                best_hook=rec.compatibility.best_hook_label,
                opener_style="",
                opener_generated="",
                opener_used="",
                aryan_approved=False,
                aryan_edited=False,
                user_action="skip",
                like_sent=False,
                extra={"frames_dir": frames_dir, "assist_send": assist_send, **base_extra},
            )
            if assist_send:
                from wingman.send_action import send_skip

                send_skip()
            else:
                print("[dry_run] Logged SKIP. Advance profile manually on phone.")
            return {"action": "skip"}

        if cmd == "r":
            return {"action": "regenerate"}

        if cmd in ("l", "like") and not rec.openers:
            from wingman.opener import generate_openers
            from dataclasses import replace

            print("  Generating openers (human override LIKE)…")
            like_compat = replace(rec.compatibility, decision="like")
            openers, rs, rr = generate_openers(rec.profile, like_compat)
            rec.openers = openers
            rec.recommended_style = rs
            rec.recommended_reason = rr
            rec.compatibility = like_compat
            if not openers:
                print("  No openers generated — use c for custom comment.")
                continue
            print("\nOPENERS (override LIKE):")
            for i, o in enumerate(rec.openers, 1):
                flag = "" if o.valid else f" [INVALID: {o.rejection_reason}]"
                print(f"  [{i}] {o.style.capitalize()}: {o.text}{flag}")
            continue

        if cmd in ("c", "comment"):
            custom = input("Your comment (bot will send on Hinge): ").strip()
            if not custom:
                continue
            best = rec.profile.best_hook()
            sent_ok = False
            record_feedback(
                profile_id=profile_id,
                ai_decision=rec.compatibility.decision,
                decision_reason="; ".join(rec.compatibility.why),
                best_hook=best.label if best else rec.compatibility.best_hook_label,
                opener_style="custom",
                opener_generated="",
                opener_used=custom,
                aryan_approved=True,
                aryan_edited=True,
                user_action="custom_assist" if assist_send else "custom",
                like_sent=False,
                extra={"frames_dir": frames_dir, "assist_send": assist_send, "human_override": True, **base_extra},
            )
            if assist_send:
                from wingman.send_action import AssistSendError, send_like_with_comment

                try:
                    send_result = send_like_with_comment(custom)
                    sent_ok = send_result.get("verified", False)
                except AssistSendError as e:
                    print(f"\n[assist-send] FAILED: {e}")
                    print("  Paste manually:\n  " + (e.comment or custom))
                    return {
                        "action": "approved",
                        "edited": custom,
                        "sent": False,
                        "send_failed": True,
                    }
            else:
                print(f"[dry_run] Logged custom. Copy to phone:\n  {custom}")
            return {
                "action": "approved",
                "edited": custom,
                "sent": sent_ok if assist_send else False,
                "send_failed": assist_send and not sent_ok,
            }

        if cmd in ("1", "2", "3") and not rec.openers:
            print("  No openers (SKIP). Use: l = like anyway | c = custom comment | s = skip")
            continue

        if cmd in ("1", "2", "3") and rec.openers:
            idx = int(cmd) - 1
            if idx >= len(rec.openers):
                print("Invalid opener number.")
                continue
            chosen = rec.openers[idx]
            if not chosen.valid:
                print(f"Warning: opener flagged invalid ({chosen.rejection_reason}). "
                      "Pick another or edit with 'e'.")
                continue
            sent_ok = False
            record_feedback(
                profile_id=profile_id,
                ai_decision=rec.compatibility.decision,
                decision_reason="; ".join(rec.compatibility.why),
                best_hook=chosen.hook_used,
                opener_style=chosen.style,
                opener_generated=chosen.text,
                opener_used=chosen.text,
                aryan_approved=True,
                aryan_edited=False,
                user_action="approve_assist" if assist_send else "approve",
                like_sent=False,
                extra={"frames_dir": frames_dir, "assist_send": assist_send, **base_extra},
            )
            if assist_send:
                from wingman.send_action import AssistSendError, send_like_with_comment

                try:
                    send_result = send_like_with_comment(chosen.text)
                    sent_ok = send_result.get("verified", False)
                except AssistSendError as e:
                    print(f"\n[assist-send] FAILED: {e}")
                    print("  Phone must be on THIS profile, scrolled to the top.")
                    print("  Paste manually:\n  " + (e.comment or chosen.text))
                    return {
                        "action": "approved",
                        "opener": chosen,
                        "sent": False,
                        "send_failed": True,
                    }
            else:
                print(f"[dry_run] Logged approval. Copy to phone:\n  {chosen.text}")
            return {
                "action": "approved",
                "opener": chosen,
                "sent": sent_ok if assist_send else False,
                "send_failed": assist_send and not sent_ok,
            }

        if cmd == "e" and not rec.openers:
            print("  No openers yet. Use l (like anyway) or c (custom comment).")
            continue

        if cmd == "e" and rec.openers:
            pick = input("Edit which opener (1/2/3)? ").strip()
            if pick not in ("1", "2", "3"):
                continue
            base = rec.openers[int(pick) - 1]
            edited = input("Your edited opener: ").strip()
            sent_ok = False
            record_feedback(
                profile_id=profile_id,
                ai_decision=rec.compatibility.decision,
                decision_reason="; ".join(rec.compatibility.why),
                best_hook=base.hook_used,
                opener_style=base.style,
                opener_generated=base.text,
                opener_used=edited,
                aryan_approved=True,
                aryan_edited=True,
                user_action="edit_assist" if assist_send else "edit",
                like_sent=False,
                extra={"frames_dir": frames_dir, "assist_send": assist_send, **base_extra},
            )
            if assist_send:
                from wingman.send_action import AssistSendError, send_like_with_comment

                try:
                    send_result = send_like_with_comment(edited)
                    sent_ok = send_result.get("verified", False)
                except AssistSendError as e:
                    print(f"\n[assist-send] FAILED: {e}")
                    print("  Paste manually:\n  " + (e.comment or edited))
                    return {
                        "action": "approved",
                        "opener": base,
                        "edited": edited,
                        "sent": False,
                        "send_failed": True,
                    }
            else:
                print(f"[dry_run] Logged edit. Copy to phone:\n  {edited}")
            return {
                "action": "approved",
                "opener": base,
                "edited": edited,
                "sent": sent_ok if assist_send else False,
                "send_failed": assist_send and not sent_ok,
            }

        print("Unknown command. Use 1/2/3, l, c, e, s, r, q.")
