"""Ollama backend for HingeAuto judging.

Targets a vision-capable model running on either:
  - Local Ollama  (`ollama serve` on your machine, default
    `http://localhost:11434`)
  - Ollama Cloud  (https://ollama.com — free tier available; set
    `OLLAMA_HOST=https://ollama.com` and `OLLAMA_API_KEY=...`)

The same JSON tool schema as the Anthropic backend is used (via
`judge_common.DECIDE_INPUT_SCHEMA`), but Ollama's tool format is
OpenAI-compatible so it gets wrapped differently.

Honest tradeoff vs Anthropic: open vision models (`qwen2.5-vl`,
`llama3.2-vision`) are noticeably less reliable at extracting structured
output across a 7-frame profile, and the opener writing is weaker. Cost
is the win — free if you self-host or stay inside Ollama Cloud's free
tier.

Set in config.py:
  JUDGE_BACKEND = "ollama"
  OLLAMA_MODEL  = "qwen2.5-vl"        # or "llama3.2-vision"
  OLLAMA_HOST   = None                # default localhost; cloud:
                                      # "https://ollama.com"

Set in your .env (or shell):
  OLLAMA_API_KEY=...   # required for Ollama Cloud, ignored locally
"""

import base64
import io
import json
import os

from PIL import Image

import config
from judge_common import (
    DECIDE_INPUT_SCHEMA,
    Decision,
    build_system_prompt,
    enforce_premade_verbatim,
)


def _client():
    try:
        from ollama import Client
    except ImportError as e:
        raise RuntimeError(
            "The `ollama` package isn't installed. Run "
            "`pip install ollama` (or install the optional extras: "
            "`pip install -r requirements-ollama.txt`)."
        ) from e

    host = getattr(config, "OLLAMA_HOST", None) or os.environ.get(
        "OLLAMA_HOST", "http://localhost:11434"
    )
    kwargs = {"host": host}
    api_key = os.environ.get("OLLAMA_API_KEY")
    if api_key:
        kwargs["headers"] = {"Authorization": f"Bearer {api_key}"}
    return Client(**kwargs)


def _tool_spec() -> dict:
    """OpenAI-compatible tool envelope wrapping the shared schema."""
    return {
        "type": "function",
        "function": {
            "name": "submit_decision",
            "description": "Submit a like/skip decision for this Hinge profile.",
            "parameters": DECIDE_INPUT_SCHEMA,
        },
    }


def _images_b64(frames: list[bytes]) -> list[str]:
    return [base64.standard_b64encode(f).decode("utf-8") for f in frames]


def _prepare_frames(frames: list[bytes]) -> list[bytes]:
    """Downscale frames so small-context vision models can fit prompt + image."""
    max_w = getattr(config, "OLLAMA_MAX_IMAGE_WIDTH", 560)
    if not max_w:
        return frames
    prepared: list[bytes] = []
    for png in frames:
        img = Image.open(io.BytesIO(png))
        if img.width > max_w:
            ratio = max_w / img.width
            img = img.resize(
                (max_w, max(1, int(img.height * ratio))),
                Image.Resampling.LANCZOS,
            )
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="PNG", optimize=True)
        prepared.append(buf.getvalue())
    return prepared


def _decision_from_args(args: dict, usage: dict) -> Decision:
    """Build Decision from a tool-call argument dict, tolerating mild
    schema drift (open models miss keys more often than Claude)."""
    defaults = {
        "name": "unknown",
        "decision": "skip",
        "confidence": "low",
        "reasoning": "",
        "message": "",
        "skip_reason": "other",
        "message_archetype": "empty",
        "premade_id": "",
        "prompt_referenced": "",
    }
    merged = {**defaults, **{k: v for k, v in args.items() if k in defaults}}
    # Clamp enum-like fields to allowed values
    if merged["decision"] not in ("like", "skip"):
        merged["decision"] = "skip"
    if merged["confidence"] not in ("low", "medium", "high"):
        merged["confidence"] = "low"
    return Decision(**merged, usage=usage)


def _usage_from_response(response) -> dict:
    return {
        "input_tokens": getattr(response, "prompt_eval_count", 0) or 0,
        "output_tokens": getattr(response, "eval_count", 0) or 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }


def _message_content(response) -> str:
    message = response.get("message") if isinstance(response, dict) else response.message
    return (
        message.get("content") if isinstance(message, dict)
        else getattr(message, "content", "")
    ) or ""


def _decision_from_response(response) -> Decision | None:
    usage = _usage_from_response(response)
    message = response.get("message") if isinstance(response, dict) else response.message
    tool_calls = (
        message.get("tool_calls") if isinstance(message, dict)
        else getattr(message, "tool_calls", None)
    ) or []

    for call in tool_calls:
        fn = call["function"] if isinstance(call, dict) else call.function
        name = fn["name"] if isinstance(fn, dict) else fn.name
        args = fn["arguments"] if isinstance(fn, dict) else fn.arguments
        if name != "submit_decision":
            continue
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        decision = _decision_from_args(args, usage)
        enforce_premade_verbatim(decision)
        return decision

    content = _message_content(response)
    if content:
        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(content[start : end + 1])
                decision = _decision_from_args(data, usage)
                enforce_premade_verbatim(decision)
                return decision
            except json.JSONDecodeError:
                pass
    return None


_JSON_SUFFIX = """

Respond with ONLY one JSON object and no other text. Required keys:
name, decision, confidence, reasoning, message, skip_reason,
message_archetype, premade_id, prompt_referenced.

decision must be "like" or "skip".
confidence must be "low", "medium", or "high".
skip_reason must be "none", "age", "preferences", "low_effort", or "other".
message_archetype must be one of: empty, observation_question, prompt_callback,
photo_callback, tease, premade, other.
Use empty strings where appropriate. Plain ASCII in message."""


def _chat_json(client, model: str, frames: list[bytes], user_text: str):
    return client.chat(
        model=model,
        messages=[
            {
                "role": "system",
                "content": build_system_prompt().strip() + _JSON_SUFFIX,
            },
            {
                "role": "user",
                "content": user_text,
                "images": _images_b64(_prepare_frames(frames)),
            },
        ],
        format="json",
        options={"temperature": 0.2},
    )


def judge(frames: list[bytes]) -> Decision:
    """Given an ordered list of PNG frames of one profile, return a Decision."""
    client = _client()
    model = getattr(config, "OLLAMA_MODEL", "qwen2.5-vl")
    use_tools = getattr(config, "OLLAMA_USE_TOOLS", True)

    user_text = (
        f"Above are {len(frames)} screenshots of one Hinge profile, in order "
        "from top to bottom. Decide whether to like or skip."
    )
    if use_tools:
        user_text += " Call the submit_decision tool with the structured result."

    response = None
    if use_tools:
        try:
            response = client.chat(
                model=model,
                messages=[
                    {"role": "system", "content": build_system_prompt()},
                    {
                        "role": "user",
                        "content": user_text,
                        "images": _images_b64(_prepare_frames(frames)),
                    },
                ],
                tools=[_tool_spec()],
                options={"temperature": 0.2},
            )
        except Exception as e:
            if "does not support tools" not in str(e):
                raise
            response = _chat_json(client, model, frames, user_text)
    else:
        response = _chat_json(client, model, frames, user_text)

    decision = _decision_from_response(response)
    if decision is not None:
        return decision

    raise RuntimeError(
        f"Ollama ({model}) did not return a usable decision. "
        f"Try OLLAMA_USE_TOOLS=False or a different OLLAMA_MODEL."
    )
