"""Shared OpenAI Responses helpers for golden-answer generation and judging."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_MODEL = "gpt-6.1-sol"


def load_env() -> dict[str, str]:
    env_file = _REPO_ROOT / ".env.local"
    env: dict[str, str] = {}
    if not env_file.exists():
        return env
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def resolve_api_key(env: dict[str, str] | None = None) -> str:
    env = env if env is not None else load_env()
    return os.environ.get("OPENAI_API_KEY") or env.get("OPENAI_API_KEY", "")


def resolve_model(env: dict[str, str] | None = None) -> str:
    env = env if env is not None else load_env()
    return (
        os.environ.get("BENCH_OPENAI_MODEL")
        or env.get("BENCH_OPENAI_MODEL")
        or _DEFAULT_MODEL
    )


def complete_text(
    *,
    api_key: str,
    model: str,
    instructions: str,
    user_text: str,
    json_mode: bool = False,
) -> str:
    """Call the Responses API and return the model's text output."""
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    # json_object mode requires the word "json" in the input message itself.
    # The instructions field does not satisfy that check.
    if json_mode and "json" not in user_text.lower():
        user_text = f"{user_text}\n\nRespond with a JSON object."
    kwargs: dict[str, Any] = {
        "model": model,
        "instructions": instructions,
        "input": user_text,
    }
    if json_mode:
        kwargs["text"] = {"format": {"type": "json_object"}}
    try:
        response = client.responses.create(**kwargs)
    except TypeError:
        kwargs.pop("text", None)
        response = client.responses.create(**kwargs)

    text = getattr(response, "output_text", None)
    if isinstance(text, str) and text.strip():
        return text.strip()

    parts: list[str] = []
    for item in getattr(response, "output", []) or []:
        if getattr(item, "type", None) != "message":
            continue
        for content in getattr(item, "content", []) or []:
            chunk = getattr(content, "text", None)
            if isinstance(chunk, str) and chunk.strip():
                parts.append(chunk.strip())
    if parts:
        return "\n".join(parts)
    raise RuntimeError("OpenAI response contained no text output")


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object, tolerating a markdown fence around it."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise
        data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    return data
