"""Platform-neutral profile analysis configuration.

The pipeline evaluates dating profiles, not a particular app. UI capture and
message sending remain separate concerns; imported screenshots can therefore
be analyzed from any supported platform without app-specific automation.
"""

from __future__ import annotations

SUPPORTED_PLATFORMS = ("generic", "hinge", "bumble", "tinder", "happn")


def normalize_platform(value: str | None) -> str:
    platform = (value or "generic").strip().lower()
    if platform not in SUPPORTED_PLATFORMS:
        raise ValueError(
            f"Unsupported platform {value!r}. Choose: "
            + ", ".join(SUPPORTED_PLATFORMS)
        )
    return platform
