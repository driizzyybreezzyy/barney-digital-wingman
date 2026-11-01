"""Send approved like+comment or skip on Hinge (assisted mode only)."""

from __future__ import annotations

import config


class AssistSendError(RuntimeError):
    """Bot could not complete Hinge tap/type — user should send manually."""

    def __init__(self, message: str, *, comment: str = "") -> None:
        super().__init__(message)
        self.comment = comment


def assisted_send_enabled() -> bool:
    return (
        getattr(config, "RUN_MODE", "dry_run") == "assisted"
        and getattr(config, "AUTO_ACTION", False)
        and not getattr(config, "DRY_RUN", True)
    )


def send_like_with_comment(message: str) -> dict:
    """Tap heart, type comment, send like. Returns {verified, warnings}."""
    if getattr(config, "DRY_RUN", True):
        raise AssistSendError("send_like_with_comment refused: DRY_RUN=True", comment=message)
    if not message.strip():
        raise ValueError("empty comment")
    from main import do_like

    text = message.strip()
    print(f"\n[assist-send] Typing on Hinge ({len(text)} chars)…")
    print(f"  → {text}")
    try:
        result = do_like(text)
    except RuntimeError as e:
        raise AssistSendError(str(e), comment=text) from e
    if result.get("verified"):
        print("[assist-send] Like + comment sent (verified on screen).")
    else:
        print("[assist-send] Tap completed but NOT fully verified — check phone now.")
        for w in result.get("warnings") or []:
            print(f"  ⚠ {w}")
        print(f"  If like didn't go through, paste manually:\n  {text}")
    return result


def send_skip() -> None:
    """Advance profile without liking."""
    if getattr(config, "DRY_RUN", True):
        print("[assist-send] DRY_RUN — skip tap skipped (advance manually on phone)")
        return
    from main import do_skip

    print("\n[assist-send] Skipping profile on Hinge…")
    do_skip()
    print("[assist-send] Skip sent.")
