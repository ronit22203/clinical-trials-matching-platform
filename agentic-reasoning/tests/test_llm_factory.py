"""Offline tests for local-model endpoint readiness checks."""

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.llm_factory import LLMHealth, build_llm, check_llm_health


def _check_with_payload(model: str, payload: object) -> tuple[LLMHealth, MagicMock]:
    client = MagicMock()
    client.__enter__.return_value = client
    response = MagicMock()
    response.json.return_value = payload
    client.get.return_value = response
    with patch("src.llm_factory.httpx.Client", return_value=client):
        health = check_llm_health(model)
    return health, client


@pytest.mark.parametrize(
    ("model", "payload", "expected_url"),
    [
        (
            "lmstudio/lmstudio-community/qwen3-8b",
            {
                "models": [
                    {
                        "publisher": "lmstudio-community",
                        "key": "qwen3-8b",
                        "loaded_instances": [{"id": "instance"}],
                    }
                ]
            },
            "http://localhost:1234/api/v1/models",
        ),
        (
            "sglang/Qwen/model",
            {"data": [{"id": "Qwen/model"}]},
            "http://localhost:30000/v1/models",
        ),
        (
            "ollama/qwen:latest",
            {"models": [{"name": "qwen:latest"}]},
            "http://localhost:11434/api/tags",
        ),
        (
            "ollama/qwen:latest",
            {"models": [{"model": "qwen:latest"}]},
            "http://localhost:11434/api/tags",
        ),
    ],
)
def test_health_accepts_usable_model_list(
    model: str, payload: object, expected_url: str
) -> None:
    health, client = _check_with_payload(model, payload)

    assert isinstance(health, LLMHealth)
    assert health.available is True
    assert health.detail is None
    client.get.assert_called_once_with(expected_url)


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        ("lmstudio/model", {"models": []}),
        ("sglang/model", {"data": []}),
        ("ollama/model", {"models": []}),
    ],
)
def test_health_rejects_empty_model_list(model: str, payload: object) -> None:
    health, _ = _check_with_payload(model, payload)

    assert health.available is False
    assert health.detail is not None
    assert "No usable models" in health.detail
    assert "retry" in health.detail


def test_health_rejects_downloaded_but_unloaded_lmstudio_model() -> None:
    health, _ = _check_with_payload(
        "lmstudio/lmstudio-community/qwen3-8b",
        {
            "models": [
                {
                    "publisher": "lmstudio-community",
                    "key": "qwen3-8b",
                    "loaded_instances": [],
                }
            ]
        },
    )

    assert health.available is False
    assert health.detail is not None
    assert "No usable models" in health.detail


def test_health_accepts_loaded_lmstudio_instance_alias() -> None:
    health, _ = _check_with_payload(
        "lmstudio/request-alias",
        {
            "models": [
                {
                    "publisher": "lmstudio-community",
                    "key": "qwen3-8b",
                    "loaded_instances": [{"id": "request-alias"}],
                }
            ]
        },
    )

    assert health.available is True


def test_health_rejects_wrong_configured_model() -> None:
    health, _ = _check_with_payload(
        "ollama/qwen2.5:7b",
        {"models": [{"name": "llama3:8b"}]},
    )

    assert health.available is False
    assert health.detail == "Configured model is not available: qwen2.5:7b."


def test_health_rejects_wrong_qualified_model_namespace() -> None:
    health, _ = _check_with_payload(
        "sglang/expected/model",
        {"data": [{"id": "other/model"}]},
    )

    assert health.available is False
    assert health.detail == "Configured model is not available: expected/model."


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        ("lmstudio/model", {}),
        ("lmstudio/model", {"models": "not-a-list"}),
        ("lmstudio/model", {"models": [{}]}),
        ("sglang/model", {"data": [{"id": "  "}]}),
        ("ollama/model", {"models": [{"name": "", "model": ""}]}),
        ("ollama/model", {"data": [{"id": "wrong-schema"}]}),
    ],
)
def test_health_rejects_malformed_model_list(model: str, payload: object) -> None:
    health, _ = _check_with_payload(model, payload)

    assert health.available is False
    assert health.detail is not None
    assert "Malformed model-list response" in health.detail


def test_health_rejects_invalid_json() -> None:
    client = MagicMock()
    client.__enter__.return_value = client
    response = MagicMock()
    response.json.side_effect = json.JSONDecodeError("bad JSON", "", 0)
    client.get.return_value = response

    with patch("src.llm_factory.httpx.Client", return_value=client):
        health = check_llm_health("lmstudio/model")

    assert health.available is False
    assert health.detail is not None
    assert "expected JSON" in health.detail


def test_health_preserves_transport_error_detail() -> None:
    client = MagicMock()
    client.__enter__.return_value = client
    client.get.side_effect = httpx.ConnectError("connection refused")

    with patch("src.llm_factory.httpx.Client", return_value=client):
        health = check_llm_health("lmstudio/model", timeout_seconds=0.25)

    assert health.available is False
    assert health.detail is not None
    assert health.detail.startswith("ConnectError: connection refused")


def test_ollama_build_maps_max_tokens_to_num_predict() -> None:
    with patch("langchain_ollama.ChatOllama") as chat:
        build_llm(
            "ollama/medgemma:4b",
            temperature=0.1,
            max_tokens=1024,
            top_p=0.9,
            frequency_penalty=0.0,
            presence_penalty=0.0,
        )

    kwargs = chat.call_args.kwargs
    assert kwargs["model"] == "medgemma:4b"
    assert kwargs["num_predict"] == 1024
    assert kwargs["temperature"] == 0.1
    assert kwargs["top_p"] == 0.9
    assert "max_tokens" not in kwargs
    assert "frequency_penalty" not in kwargs
    assert "presence_penalty" not in kwargs


def test_ollama_build_keeps_explicit_num_predict() -> None:
    with patch("langchain_ollama.ChatOllama") as chat:
        build_llm("ollama/medgemma:4b", max_tokens=1024, num_predict=256)

    assert chat.call_args.kwargs["num_predict"] == 256
    assert "max_tokens" not in chat.call_args.kwargs


def test_openai_compatible_build_keeps_max_tokens() -> None:
    with patch("langchain_openai.ChatOpenAI") as chat:
        build_llm("lmstudio/qwen3-8b", max_tokens=1024, temperature=0.1)

    kwargs = chat.call_args.kwargs
    assert kwargs["max_tokens"] == 1024
    assert kwargs["temperature"] == 0.1
    assert "num_predict" not in kwargs
