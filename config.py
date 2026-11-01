"""Configuration for HingeAuto.

PREFERENCES, AGE_MIN/MAX, and MESSAGE_VOICE come from the active mode (see
`modes/`). Set ACTIVE_MODE here for the persistent default; override per-run
via `python main.py --mode <name>`.

The COORDS defaults below are calibrated for a Pixel 10 emulator
(1080x2424). If that's what you're running and Hinge hasn't shifted
its layout, they should work as-is. Otherwise run `python calibrate.py`
and update the values that don't match your device.
"""

from pathlib import Path

# ---------- Mode selection ----------
# Which `modes/<name>.py` to load. Overridden per-run by `python main.py --mode X`.
ACTIVE_MODE = "example_lenient"

# These get filled in by _apply_mode() at the bottom of this file. Declared
# here so static analyzers / IDEs see them. Do not edit by hand — edit the
# mode module instead.
PREFERENCES: str = ""
AGE_MIN: int | None = None
AGE_MAX: int | None = None
MESSAGE_VOICE: str | None = None
MODE_NAME: str = ""
PREMADES: list[dict] = []

# ---------- Digital Wingman run modes (see DIGITAL_WINGMAN.md §27) ----------
#   dry_run    — capture + judge only; no taps on Hinge (Mode 0)
#   wingman    — judge + human approval; user sends action (Mode 1)
#   assisted   — judge + approval, then bot performs tap (Mode 2)
#   automated  — full auto loop (Mode 3; disabled by default)
RUN_MODE = "dry_run"

# Human-in-the-loop defaults (Digital Wingman experiment).
HUMAN_APPROVAL = True
AUTO_ACTION = False

# When automating likes: prefer profiles showing "Active now" on Hinge.
# In assisted/automated mode, inactive profiles are deferred unless LIKE ≥9/10
# or 3+ tier-1 hooks — saves free daily likes for better reply odds.
PREFER_ACTIVE_NOW = True

# Prefer LLM openers (varied voice). Fallbacks only when generation fails.
OPENER_FALLBACK_FIRST = False

# Automated likes: skip thin (1 prompt) profiles unless Active now.
AUTOMATE_REQUIRE_ACTIVE_NOW = True

# Legacy hinge-auto flag. Still honored when RUN_MODE == "automated":
#   DRY_RUN = False -> actually like / send messages
#   DRY_RUN = True  -> decide and log, but force-skip every profile
#                       instead of liking (profile leaves queue; no like spent).
DRY_RUN = True

# Default = 8, which matches free-tier Hinge's daily like cap (resets at
# 4am local). One session per day exhausts the free allotment cleanly.
#
# If you have Hinge+ (no daily cap), bump this to ~25-50 per session and
# run multiple sessions throughout the day. Going much higher per session
# tends to trigger Hinge's soft-throttle (empty Discover after a burst);
# spacing batches across the day works better than one giant batch.
MAX_LIKES_PER_SESSION = 8
MAX_PROFILES_PER_SESSION = 100

# ---------- Device / screen ----------
# Leave unset to auto-detect a single connected emulator/device. Set this
# locally when multiple ADB devices are connected.
ADB_SERIAL = None
SCREEN_WIDTH = 1240
SCREEN_HEIGHT = 2772

# Keep capture bounded. The capture loop stops earlier when consecutive
# screenshots are visually unchanged.
FRAMES_PER_PROFILE = 6
SELF_PROFILE_MAX_FRAMES = 8
DISCOVER_PROFILE_MAX_FRAMES = 8

# Human-like scroll jitter (reduces fixed-gesture bot pattern).
HUMAN_SCROLL = True

# Set True after post-capture scroll-to-top so do_like skips the long scroll sweep.
PROFILE_AT_TOP_AFTER_CAPTURE = False

# ---------- Coordinates (reference: Pixel 10 @ 1080x2424, auto-scaled) ----------
_COORDS_REF = {
    # Skip / like action targets (Discover screen, photo 1 at top)
    # Calibrated OnePlus 11R @ 1240x2772 (2026-09-02, profile S).
    "skip_button":       (368, 1424),   # X icon on prompt card
    "heart_photo_1":     (935, 1418),   # Heart icon on photo 1

    # Compose box fallbacks (vision re-finds at tap-time when possible).
    "send_like_button":  (711, 1359),
    "comment_input":     (470, 1209),
    "compose_close":     (960, 200),

    # Scroll gesture (swipe up = scroll down through profile).
    "scroll_from":       (540, 1700),
    "scroll_to":         (540, 700),
    "scroll_duration_ms": 350,

    # Bottom nav (5 evenly-spaced icons across the bottom strip).
    "nav_discover":      (108, 2270),
    "nav_standouts":     (324, 2270),
    "nav_likes_you":     (540, 2270),
    "nav_matches":       (756, 2270),
    "nav_self_pfp":      (972, 2270),

    # Self-profile flow (used by scan_self.py — "what does my profile
    # look like to others"). From Discover: nav_self_pfp → self_avatar →
    # view_tab gets you to a scrollable view of your own profile. Then
    # back_arrow → back_arrow → nav_discover to return.
    "self_avatar":       (540, 497),    # circle avatar on self tab
    "view_tab":          (810, 310),    # 'View' tab on profile editor
    "back_arrow":        (65, 200),     # top-left back arrow

    # Discover filter row (tap the chip to open its bottom sheet).
    "sliders_icon":      (95, 225),     # opens Dating Preferences
    "age_chip":          (460, 225),    # opens Age filter sheet
}

from coords_util import scale_coords  # noqa: E402

COORDS = scale_coords(_COORDS_REF, SCREEN_WIDTH, SCREEN_HEIGHT)

# ---------- Timing ----------
# Random delay between actions (seconds, min/max for jitter).
DELAYS = {
    "after_scroll":     (0.6, 1.0),
    "after_screenshot": (0.2, 0.4),
    "after_tap":        (0.8, 1.4),
    "after_like_sent":  (2.5, 4.0),
    "after_skip":       (1.5, 2.5),
}

# ---------- Judge backend ----------
# "anthropic" -> uses your ANTHROPIC_API_KEY; best quality, ~$0.02-0.05/profile.
# "ollama"    -> uses Ollama Cloud (free tier) or local Ollama; lower quality
#                but no per-token cost.
# "gemini"    -> uses Google Gemini API; free tier up to 15 RPM, very fast.
JUDGE_BACKEND = "gemini"

# ---------- Gemini settings (when JUDGE_BACKEND == "gemini") ----------
# Requires GEMINI_API_KEY in your environment or .env file.
GEMINI_MODEL = "gemini-2.5-flash"

# ---------- Anthropic settings (when JUDGE_BACKEND == "anthropic") ----------
# Sonnet is the default — cheaper than Opus and plenty capable for this task.
# Switch to "claude-opus-4-7" if you want top-quality judgment, or
# "claude-haiku-4-5" for cheapest (may miss subtle cues).
MODEL = "claude-sonnet-4-6"
EFFORT = "medium"  # low | medium | high

# ---------- Ollama settings (when JUDGE_BACKEND == "ollama") ----------
# Vision-capable models that handle multiple images per turn:
#   "qwen2.5-vl"        — strong all-around vision model (recommended)
#   "qwen2.5-vl:7b"     — smaller, faster, weaker
#   "llama3.2-vision"   — alternative; tool-calling can be flakier
OLLAMA_MODEL = "qwen2.5vl:3b"

# OLLAMA_HOST: None or "" -> default http://localhost:11434
#              "https://ollama.com" -> Ollama Cloud (requires OLLAMA_API_KEY)
# Can also be set via the OLLAMA_HOST environment variable.
OLLAMA_HOST = "http://127.0.0.1:11434"

# qwen2.5vl:3b does not support Ollama tool-calling; use JSON-in-content instead.
OLLAMA_USE_TOOLS = False

# Downscale screenshots before Ollama vision (3b model ctx = 4096 tokens).
OLLAMA_MAX_IMAGE_WIDTH = 560

# ---------- Paths ----------
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DEBUG_DIR = BASE_DIR / "debug"
SCREENSHOTS_DIR = BASE_DIR / "screenshots"
SAVE_DEBUG_FRAMES = True  # keep frames + decisions in debug/ for review


def _apply_mode() -> None:
    """Resolve ACTIVE_MODE and populate this module's PREFERENCES /
    AGE_MIN / AGE_MAX / MESSAGE_VOICE / MODE_NAME / cap overrides.

    Re-entrant — main.py calls this again after parsing --mode so a CLI
    override takes effect before the judge sees config.
    """
    import modes
    mode = modes.load(ACTIVE_MODE)
    g = globals()
    g["PREFERENCES"] = mode.PREFERENCES
    g["AGE_MIN"] = getattr(mode, "AGE_MIN", None)
    g["AGE_MAX"] = getattr(mode, "AGE_MAX", None)
    g["MESSAGE_VOICE"] = getattr(mode, "MESSAGE_VOICE", None)
    g["MODE_NAME"] = mode.NAME
    g["PREMADES"] = list(getattr(mode, "PREMADES", []))
    for k in ("MAX_LIKES_PER_SESSION", "MAX_PROFILES_PER_SESSION"):
        v = getattr(mode, k, None)
        if v is not None:
            g[k] = v


_apply_mode()
