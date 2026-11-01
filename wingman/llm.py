"""Shared LLM vision + JSON helpers for Wingman pipeline.

Supports both Ollama and Gemini backends depending on config.JUDGE_BACKEND.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable

import config
import judge_ollama

# Tunable output limits per call type (3B models truncate easily below these).
DEFAULT_TEXT_NUM_PREDICT = 2048
VISION_NUM_PREDICT = 2048
HOOKS_NUM_PREDICT = 1024
COMPAT_NUM_PREDICT = 1536
OPENERS_NUM_PREDICT = 1536


def _parse_json_content(content: str) -> dict[str, Any]:
    content = content.strip()
    if not content:
        raise RuntimeError("LLM returned empty content")
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        data = _salvage_json_object(content)
    if not isinstance(data, dict):
        raise RuntimeError(f"Expected JSON object, got {type(data).__name__}")
    return data


def _salvage_json_object(content: str) -> dict[str, Any]:
    start = content.find("{")
    if start < 0:
        raise RuntimeError(f"LLM did not return valid JSON: {content[:300]!r}")
    try:
        return json.loads(content[start:])
    except json.JSONDecodeError:
        pass
    end = content.rfind("}")
    if end > start:
        try:
            return json.loads(content[start : end + 1])
        except json.JSONDecodeError:
            pass

    salvaged = _salvage_known_arrays(content)
    if salvaged:
        return salvaged

    raise RuntimeError(f"LLM returned malformed JSON: {content[:300]!r}")


def _salvage_known_arrays(content: str) -> dict[str, Any] | None:
    if '"hooks"' in content:
        hooks = []
        for m in re.finditer(
            r'\{\s*"label"\s*:\s*"([^"]*)"\s*,\s*"detail"\s*:\s*"([^"]*)"\s*,'
            r'\s*"tier"\s*:\s*(\d+)\s*,\s*"source"\s*:\s*"([^"]*)"\s*\}',
            content,
        ):
            hooks.append({
                "label": m.group(1),
                "detail": m.group(2),
                "tier": int(m.group(3)),
                "source": m.group(4),
            })
        if hooks:
            return {"hooks": hooks}

    if '"openers"' in content:
        openers = []
        for m in re.finditer(
            r'\{\s*"style"\s*:\s*"([^"]*)"\s*,\s*"text"\s*:\s*"([^"]*)"\s*,'
            r'\s*"hook_used"\s*:\s*"([^"]*)"\s*,\s*"evidence"\s*:\s*"([^"]*)"\s*\}',
            content,
        ):
            openers.append({
                "style": m.group(1),
                "text": m.group(2),
                "hook_used": m.group(3),
                "evidence": m.group(4),
            })
        if openers:
            result: dict[str, Any] = {"openers": openers}
            for key, pattern in (
                ("recommended_style", r'"recommended_style"\s*:\s*"([^"]*)"'),
                ("recommended_reason", r'"recommended_reason"\s*:\s*"([^"]*)"'),
            ):
                rm = re.search(pattern, content)
                if rm:
                    result[key] = rm.group(1)
            return result

    if '"decision"' in content:
        decision_m = re.search(r'"decision"\s*:\s*"(like|skip)"', content)
        score_m = re.search(r'"confidence_score"\s*:\s*(\d+)', content)
        if decision_m:
            return {
                "decision": decision_m.group(1),
                "confidence_score": int(score_m.group(1)) if score_m else 5,
                "why": [],
                "compatibility_signals": [],
                "incompatibility_signals": [],
                "best_hook_label": "",
            }

    return None


def _gemini_chat(system: str, user: str, frames: list[bytes] = None) -> tuple[dict[str, Any], dict]:
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY environment variable is not set. Please add it to your .env file.")

    client = genai.Client(api_key=api_key)
    model = getattr(config, "GEMINI_MODEL", "gemini-2.5-flash")

    contents = []
    if frames:
        for frame_bytes in frames:
            contents.append(
                types.Part.from_bytes(data=frame_bytes, mime_type="image/png")
            )

    contents.append(
        types.Part.from_text(text=user)
    )

    generate_config = types.GenerateContentConfig(
        system_instruction=system.strip(),
        response_mime_type="application/json",
        temperature=0.2,
    )

    try:
        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=generate_config,
        )
    except Exception as e:
        raise RuntimeError(f"Gemini API call failed: {e}") from e

    usage = {
        "input_tokens": response.usage_metadata.prompt_token_count if response.usage_metadata else 0,
        "output_tokens": response.usage_metadata.candidates_token_count if response.usage_metadata else 0,
    }

    if not response.text:
        raise RuntimeError("Gemini returned an empty response.")

    return _parse_json_content(response.text), usage


def _chat(
    client,
    model: str,
    messages: list[dict],
    *,
    retries: int = 2,
    num_predict: int = DEFAULT_TEXT_NUM_PREDICT,
    on_retry: Callable[[int], list[dict]] | None = None,
) -> tuple[dict, dict]:
    last_err: Exception | None = None
    total_usage = {"input_tokens": 0, "output_tokens": 0}

    for attempt in range(retries + 1):
        attempt_messages = messages
        if attempt > 0 and on_retry:
            attempt_messages = on_retry(attempt)

        response = client.chat(
            model=model,
            messages=attempt_messages,
            format="json",
            options={
                "temperature": 0.2 if attempt == 0 else 0.1,
                "num_predict": num_predict,
            },
        )
        usage = judge_ollama._usage_from_response(response)
        total_usage["input_tokens"] += usage.get("input_tokens", 0)
        total_usage["output_tokens"] += usage.get("output_tokens", 0)
        content = judge_ollama._message_content(response)
        try:
            return _parse_json_content(content), total_usage
        except RuntimeError as e:
            last_err = e
            if attempt < retries:
                continue
    raise last_err or RuntimeError("Ollama JSON call failed")


def vision_json(system: str, user: str, frames: list[bytes]) -> tuple[dict[str, Any], dict]:
    """Send screenshot(s) to the LLM and parse a JSON object from the response."""
    backend = getattr(config, "JUDGE_BACKEND", "ollama").lower()
    if backend == "gemini":
        return _gemini_chat(system, user, frames)

    client = judge_ollama._client()
    model = getattr(config, "OLLAMA_MODEL", "qwen2.5vl:3b")
    messages = [
        {"role": "system", "content": system.strip()},
        {
            "role": "user",
            "content": user,
            "images": judge_ollama._images_b64(judge_ollama._prepare_frames(frames)),
        },
    ]
    return _chat(client, model, messages, retries=1, num_predict=VISION_NUM_PREDICT)


def text_json(
    system: str,
    user: str,
    *,
    num_predict: int = DEFAULT_TEXT_NUM_PREDICT,
    retries: int = 2,
    compact_user: str | None = None,
) -> tuple[dict[str, Any], dict]:
    """Text-only LLM JSON call (no images)."""
    backend = getattr(config, "JUDGE_BACKEND", "ollama").lower()
    if backend == "gemini":
        return _gemini_chat(system, user, None)

    client = judge_ollama._client()
    model = getattr(config, "OLLAMA_MODEL", "qwen2.5vl:3b")
    messages = [
        {"role": "system", "content": system.strip()},
        {"role": "user", "content": user},
    ]

    def on_retry(attempt: int) -> list[dict]:
        retry_user = compact_user if compact_user is not None else user
        return [
            {"role": "system", "content": system.strip()},
            {
                "role": "user",
                "content": (
                    f"{retry_user}\n\n"
                    "IMPORTANT: Return ONLY compact valid JSON. No markdown. "
                    "Keep strings short. Do not truncate mid-string."
                ),
            },
        ]

    return _chat(
        client,
        model,
        messages,
        retries=retries,
        num_predict=num_predict,
        on_retry=on_retry if (compact_user is not None or retries > 0) else None,
    )
