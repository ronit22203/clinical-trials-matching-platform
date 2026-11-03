"""Offline checks for which server the inference benchmark calls."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from inference_evaluator import resolve_inference_endpoint


def test_ollama_agent_ignores_lm_studio_url() -> None:
    base_url, model = resolve_inference_endpoint(
        {"agentic_reasoning": {"agent": {"model": "ollama/medgemma:4b"}}},
        {
            "LM_STUDIO_BASE_URL": "http://localhost:1234/v1",
            "OLLAMA_BASE_URL": "http://localhost:11434",
        },
    )
    assert model == "medgemma:4b"
    assert base_url == "http://127.0.0.1:11434/v1"


def test_lmstudio_agent_uses_its_own_url() -> None:
    base_url, model = resolve_inference_endpoint(
        {"agentic_reasoning": {"agent": {"model": "lmstudio/qwen3-8b"}}},
        {"LM_STUDIO_BASE_URL": "http://localhost:1234/v1"},
    )
    assert model == "qwen3-8b"
    assert base_url == "http://127.0.0.1:1234/v1"


def test_explicit_base_url_is_kept() -> None:
    base_url, model = resolve_inference_endpoint(
        {"agentic_reasoning": {"agent": {"model": "ollama/medgemma:4b"}}},
        {},
        base_url="http://localhost:11434/v1",
    )
    assert model == "medgemma:4b"
    assert base_url == "http://127.0.0.1:11434/v1"
