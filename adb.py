"""Thin wrapper around `adb` commands."""

import random
import shlex
import subprocess
import time

import config
from coords_util import bottom_nav_x


def _serial_prefix() -> list[str]:
    """Return ['-s', serial] when config.ADB_SERIAL is set."""
    serial = getattr(config, "ADB_SERIAL", None)
    if serial:
        return ["-s", serial]
    return []


def _run(args: list[str], capture: bool = False) -> bytes | None:
    cmd = ["adb"] + _serial_prefix() + args
    if capture:
        result = subprocess.run(cmd, capture_output=True, check=True)
        return result.stdout
    subprocess.run(cmd, check=True)
    return None


def list_devices() -> list[str]:
    """Return serials of connected ADB devices in `device` state."""
    # Always query the global device list (no -s prefix).
    out = subprocess.run(
        ["adb", "devices"], capture_output=True, check=True,
    ).stdout.decode()
    return [
        line.split("\t")[0]
        for line in out.splitlines()[1:]
        if line.strip() and "\tdevice" in line
    ]


def check_device() -> str:
    """Raise if no device is connected. Return the active device serial."""
    devices = list_devices()
    if not devices:
        raise RuntimeError(
            "No ADB device found. Connect your phone/emulator and run `adb devices`."
        )
    preferred = getattr(config, "ADB_SERIAL", None)
    if preferred:
        if preferred not in devices:
            raise RuntimeError(
                f"ADB_SERIAL={preferred!r} not connected. "
                f"Available: {', '.join(devices)}"
            )
        return preferred
    if len(devices) > 1:
        raise RuntimeError(
            "Multiple ADB devices connected. Set config.ADB_SERIAL to one of: "
            + ", ".join(devices)
        )
    return devices[0]


def screenshot() -> bytes:
    """Return PNG bytes of the current screen."""
    return _run(["exec-out", "screencap", "-p"], capture=True)


def tap(x: int, y: int) -> None:
    _run(["shell", "input", "tap", str(x), str(y)])


def press_back() -> None:
    """Android BACK — dismiss sheets, notification shade, compose card."""
    _run(["shell", "input", "keyevent", "4"])


def tap_nav_profile() -> None:
    """Bottom-right profile tab — computed from screen width."""
    y = config.COORDS["nav_self_pfp"][1]
    x = bottom_nav_x(4, config.SCREEN_WIDTH)
    tap(x, y)


def input_text(text: str) -> None:
    """Type `text` into the currently focused field via `adb shell input text`.

    Single-quotes the payload with shlex so $, `, ", and spaces survive the
    device shell. Caller should keep text plain ASCII — emoji and the chars
    \\ " $ ` should be filtered upstream (the model is instructed to avoid
    them) since `input text` itself only sends keyevents.
    """
    quoted = shlex.quote(text)
    _run(["shell", f"input text {quoted}"])


def swipe(x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
    _run(["shell", "input", "swipe",
          str(x1), str(y1), str(x2), str(y2), str(duration_ms)])


def _human_scroll_endpoints(down: bool) -> tuple[tuple[int, int], tuple[int, int], int]:
    """Variable swipe path — not a fixed machine-like gesture."""
    c = config.COORDS
    (x1, y1), (x2, y2) = c["scroll_from"], c["scroll_to"]
    if not down:
        x1, y1, x2, y2 = x2, y2, x1, y1
    w = config.SCREEN_WIDTH
    jx1 = x1 + random.randint(-45, 45)
    jx2 = x2 + random.randint(-45, 45)
    jy1 = y1 + random.randint(-35, 35)
    jy2 = y2 + random.randint(-35, 35)
    jx1 = max(80, min(w - 80, jx1))
    jx2 = max(80, min(w - 80, jx2))
    base = c.get("scroll_duration_ms", 350)
    duration = random.randint(max(220, base - 120), base + 220)
    return (jx1, jy1), (jx2, jy2), duration


def scroll_down_human() -> None:
    (x1, y1), (x2, y2), duration = _human_scroll_endpoints(down=True)
    swipe(x1, y1, x2, y2, duration)
    if random.random() < 0.25:
        time.sleep(random.uniform(0.25, 0.75))


def scroll_up_human() -> None:
    (x1, y1), (x2, y2), duration = _human_scroll_endpoints(down=False)
    swipe(x1, y1, x2, y2, duration)
    if random.random() < 0.2:
        time.sleep(random.uniform(0.2, 0.55))


def scroll_down() -> None:
    if getattr(config, "HUMAN_SCROLL", True):
        scroll_down_human()
        return
    c = config.COORDS
    swipe(*c["scroll_from"], *c["scroll_to"], c["scroll_duration_ms"])


def scroll_up() -> None:
    if getattr(config, "HUMAN_SCROLL", True):
        scroll_up_human()
        return
    c = config.COORDS
    swipe(*c["scroll_to"], *c["scroll_from"], c["scroll_duration_ms"])


def jitter_sleep(key: str) -> None:
    lo, hi = config.DELAYS[key]
    time.sleep(random.uniform(lo, hi))
