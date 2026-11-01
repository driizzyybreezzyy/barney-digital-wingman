"""Load the user's local profile and preferences YAML."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

import config


def _data_dir() -> Path:
    return getattr(config, "DATA_DIR", config.BASE_DIR / "data")


@lru_cache(maxsize=1)
def load_aryan_profile() -> dict[str, Any]:
    path = _data_dir() / "aryan_profile.yaml"
    if not path.is_file():
        path = _data_dir() / "user_profile.example.yaml"
    if not path.is_file():
        raise FileNotFoundError(
            f"Missing {path}. Copy data/user_profile.example.yaml to "
            "data/aryan_profile.yaml and customize it."
        )
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError("aryan_profile.yaml must be a mapping")
    return data


@lru_cache(maxsize=1)
def load_preferences() -> dict[str, Any]:
    path = _data_dir() / "preferences.yaml"
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def personality_prompt_section() -> str:
    """Compact personality block for system prompts."""
    p = load_aryan_profile()
    lines = ["## User profile (source of truth)", ""]
    ident = p.get("identity", {})
    lines.append(f"Age: {ident.get('age')}, Location: {ident.get('location')}")
    lines.append(f"Preferred age: {ident.get('preferred_age_range')}")
    lines.append(f"Geography: {ident.get('preferred_geography')}")
    obj = p.get("dating_objective", {})
    lines.append(f"Primary goals: {obj.get('primary')}")
    lines.append(f"Secondary: {obj.get('secondary')}")
    persona = p.get("communication_persona", {})
    lines.append(f"Voice: {persona.get('target')}")
    lines.append(f"Default boldness: {persona.get('default_boldness', 7)}/10")
    never = p.get("hard_rules", {}).get("never", [])
    if never:
        lines.append("Never: " + "; ".join(str(x) for x in never[:8]) + "...")
    avoid = p.get("opener_preferences", {}).get("avoid", [])
    if avoid:
        lines.append("Opener avoid: " + ", ".join(str(x) for x in avoid))
    phrases_never = p.get("phrases_never", [])
    if phrases_never:
        lines.append("Banned phrases: " + ", ".join(str(x) for x in phrases_never))
    sel = p.get("selection_preferences", {})
    if sel.get("prioritize"):
        lines.append("Prioritize: " + ", ".join(str(x) for x in sel["prioritize"]))
    if sel.get("de_prioritize"):
        lines.append("De-prioritize: " + ", ".join(str(x) for x in sel["de_prioritize"]))
    return "\n".join(lines)


def natural_phrase_hints() -> list[str]:
    p = load_aryan_profile()
    return [str(x) for x in p.get("phrases_natural", []) if x]


def banned_phrases() -> list[str]:
    p = load_aryan_profile()
    out = [str(x).lower() for x in p.get("phrases_never", [])]
    for x in p.get("opener_preferences", {}).get("avoid", []):
        s = str(x).lower().strip()
        if s and s not in out:
            out.append(s)
    return out
