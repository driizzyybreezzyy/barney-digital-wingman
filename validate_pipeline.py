"""Phase 1 live-device validation — capture + Ollama judge, zero Hinge actions.

This script NEVER taps, swipes, types, or otherwise interacts with Hinge.
It only reads screenshots and sends them to the configured judge backend.

Usage:
  .venv/bin/python validate_pipeline.py
      # judge debug/hinge_test.png (default)

  .venv/bin/python validate_pipeline.py --live-capture
      # screencap from ADB_SERIAL, save to debug/, then judge

Safety: respects config.RUN_MODE=dry_run; performs no UI actions regardless.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image

import config
from judge_common import load_backend


DEFAULT_FIXTURE = config.DEBUG_DIR / "hinge_test.png"


def _assert_safe_config() -> None:
    if config.RUN_MODE != "dry_run":
        raise SystemExit(
            f"Refusing to run: RUN_MODE={config.RUN_MODE!r} (must be 'dry_run')"
        )
    if not config.HUMAN_APPROVAL:
        raise SystemExit("Refusing to run: HUMAN_APPROVAL must be True")
    if config.AUTO_ACTION:
        raise SystemExit("Refusing to run: AUTO_ACTION must be False")


def _load_frame(path: Path) -> bytes:
    if not path.is_file():
        raise FileNotFoundError(f"Screenshot not found: {path}")
    return path.read_bytes()


def _frame_info(png: bytes) -> str:
    img = Image.open(__import__("io").BytesIO(png))
    return f"{img.size[0]}x{img.size[1]} {img.mode}"


def _live_capture(out_path: Path) -> bytes:
    import adb

    serial = adb.check_device()
    print(f"ADB device: {serial}")
    png = adb.screenshot()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(png)
    print(f"Saved capture: {out_path} ({_frame_info(png)})")
    return png


def _print_decision(decision) -> None:
    print("\n--- Wingman analysis (log only) ---")
    print(f"Name:       {decision.name}")
    print(f"Decision:   {decision.decision} ({decision.confidence})")
    print(f"Reasoning:  {decision.reasoning}")
    if decision.message:
        print(f"Message:    {decision.message}")
    print(f"Archetype:  {decision.message_archetype}")
    print(f"Hook ref:   {decision.prompt_referenced or '(none)'}")
    print(f"Skip reason:{decision.skip_reason}")
    if decision.usage:
        print(f"Tokens:     {decision.usage}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate ADB capture + Ollama judge without Hinge interaction",
    )
    parser.add_argument(
        "--live-capture",
        action="store_true",
        help="Capture current screen via ADB (still no taps/swipes)",
    )
    parser.add_argument(
        "--image",
        type=Path,
        default=DEFAULT_FIXTURE,
        help=f"PNG to judge when not using --live-capture (default: {DEFAULT_FIXTURE})",
    )
    args = parser.parse_args()

    _assert_safe_config()

    print("Digital Wingman — pipeline validation (no Hinge interaction)")
    print(f"RUN_MODE={config.RUN_MODE}  HUMAN_APPROVAL={config.HUMAN_APPROVAL}  "
          f"AUTO_ACTION={config.AUTO_ACTION}")
    print(f"JUDGE_BACKEND={config.JUDGE_BACKEND}  OLLAMA_MODEL={config.OLLAMA_MODEL}")
    print(f"OLLAMA_HOST={config.OLLAMA_HOST or 'http://localhost:11434'}")
    print(f"ADB_SERIAL={getattr(config, 'ADB_SERIAL', None) or '(auto)'}")
    print()

    hinge_interaction_attempted = False

    if args.live_capture:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = config.DEBUG_DIR / f"validate_capture_{stamp}.png"
        png = _live_capture(out)
    else:
        png = _load_frame(args.image)
        print(f"Using fixture: {args.image} ({_frame_info(png)})")

    judge_fn = load_backend().judge
    print("\nCalling Ollama judge (single frame)...")
    decision = judge_fn([png])
    _print_decision(decision)

    report_path = config.DEBUG_DIR / "validate_pipeline_last.txt"
    report_path.write_text(
        f"timestamp: {datetime.now().isoformat(timespec='seconds')}\n"
        f"run_mode: {config.RUN_MODE}\n"
        f"hinge_interaction_attempted: {hinge_interaction_attempted}\n"
        f"source: {'live-capture' if args.live_capture else args.image}\n"
        f"name: {decision.name}\n"
        f"decision: {decision.decision}\n"
        f"confidence: {decision.confidence}\n"
        f"reasoning: {decision.reasoning}\n"
        f"message: {decision.message}\n",
        encoding="utf-8",
    )
    print(f"\nReport saved: {report_path}")
    print("Hinge interaction attempted: NO")
    return 0


if __name__ == "__main__":
    sys.exit(main())
