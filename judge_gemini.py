"""Gemini backend for HingeAuto judging.

Uses the official google-genai SDK to parse profile screenshots.
Requires GEMINI_API_KEY to be set in your environment or .env file.
"""

import json
import os

try:
    from google import genai
    from google.genai import types
except ImportError as e:
    raise RuntimeError(
        "The `google-genai` package isn't installed. Run "
        "`pip install google-genai` or install from requirements.txt."
    ) from e

import config
from judge_common import (
    DECIDE_INPUT_SCHEMA,
    Decision,
    build_system_prompt,
    enforce_premade_verbatim,
)


def judge(frames: list[bytes]) -> Decision:
    """Given an ordered list of PNG frames of one profile, return a Decision."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY environment variable is not set. Please add it to your .env file."
        )

    client = genai.Client(api_key=api_key)
    model = getattr(config, "GEMINI_MODEL", "gemini-2.5-flash")

    contents = []
    for frame_bytes in frames:
        contents.append(
            types.Part.from_bytes(data=frame_bytes, mime_type="image/png")
        )

    contents.append(
        types.Part.from_text(
            text=(
                f"Above are {len(frames)} screenshots of one Hinge profile, in order "
                "from top to bottom. Decide whether to like or skip."
            )
        )
    )

    # Note: google-genai takes JSON schema directly.
    generate_config = types.GenerateContentConfig(
        system_instruction=build_system_prompt(),
        response_mime_type="application/json",
        response_schema=DECIDE_INPUT_SCHEMA,
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
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }

    if not response.text:
        raise RuntimeError(f"Gemini returned an empty response. Finish reason: {response.candidates[0].finish_reason if response.candidates else 'unknown'}")

    try:
        data = json.loads(response.text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Gemini returned invalid JSON: {response.text}") from e
    
    # Filter keys so we only pass known dataclass fields
    known_fields = [
        "name", "decision", "confidence", "reasoning", "message",
        "skip_reason", "message_archetype", "premade_id", "prompt_referenced"
    ]
    filtered_data = {k: v for k, v in data.items() if k in known_fields}

    decision = Decision(**filtered_data, usage=usage)
    enforce_premade_verbatim(decision)
    return decision
