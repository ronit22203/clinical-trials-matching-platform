# src/llm_factory.py
"""
LLM factory: routes on the ``provider/model-name`` prefix in agent configs.

Supported providers
-------------------
- ``lmstudio/…`` — LM Studio OpenAI-compatible server (default: http://localhost:1234/v1)
                   Override via LM_STUDIO_BASE_URL environment variable.
                   Enforces JSON mode via response_format when model_params includes it.
- ``ollama/…``   — local Ollama server (default: http://localhost:11434)
                   Override via LLM_BASE_URL (preferred) or OLLAMA_BASE_URL (legacy).
- ``sglang/…``   — SGLang OpenAI-compatible server (default: http://localhost:30000/v1)
                   Override via SGLANG_BASE_URL environment variable.

Fallback
--------
If the prefix before ``/`` is not a recognised provider (e.g. a HuggingFace org such as
``mradermacher/Llama-3.1-8B-UltraMedical-GGUF``), the factory routes to LM Studio and
passes the *full* original string as the model identifier — which is exactly how LM Studio
references GGUF models loaded from HuggingFace.
Override the target server via LM_STUDIO_BASE_URL if needed.
"""
import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx
from langchain_core.language_models.chat_models import BaseChatModel

logger = logging.getLogger(__name__)

_KNOWN_PROVIDERS = {"lmstudio", "ollama", "sglang"}


@dataclass(frozen=True)
class LLMEndpoint:
    """Resolved local LLM endpoint and its provider-specific health route."""

    provider: str
    model_name: str
    base_url: str

    @property
    def health_url(self) -> str:
        if self.provider == "ollama":
            return f"{self.base_url.rstrip('/')}/api/tags"
        return f"{self.base_url.rstrip('/')}/models"


@dataclass(frozen=True)
class LLMHealth:
    """Availability result for a local LLM provider."""

    endpoint: LLMEndpoint
    available: bool
    detail: str | None = None


def resolve_llm_endpoint(model: str) -> LLMEndpoint:
    """Resolve a provider/model identifier to its configured local endpoint."""
    normalized = model.strip()
    provider, separator, model_name = normalized.partition("/")
    if not provider or not separator or not model_name.strip():
        raise ValueError(
            "LLM model must use the provider/model-name format. "
            f"Received: {model!r}"
        )

    if provider == "lmstudio":
        return LLMEndpoint(
            provider=provider,
            model_name=model_name,
            base_url=os.getenv("LM_STUDIO_BASE_URL", "http://localhost:1234/v1"),
        )

    if provider == "ollama":
        return LLMEndpoint(
            provider=provider,
            model_name=model_name,
            base_url=os.getenv("LLM_BASE_URL")
            or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        )

    if provider == "sglang":
        return LLMEndpoint(
            provider=provider,
            model_name=model_name,
            base_url=os.getenv("SGLANG_BASE_URL", "http://localhost:30000/v1"),
        )

    if provider not in _KNOWN_PROVIDERS:
        logger.warning(
            "Unknown provider prefix '%s' in model string '%s'. "
            "Routing to LM Studio with the full model identifier. "
            "Set LM_STUDIO_BASE_URL to override the server endpoint.",
            provider,
            model,
        )
        return LLMEndpoint(
            provider="lmstudio",
            model_name=normalized,
            base_url=os.getenv("LM_STUDIO_BASE_URL", "http://localhost:1234/v1"),
        )

    raise ValueError(
        f"Unsupported LLM provider '{provider}' in model string '{model}'. "
        "Supported providers: lmstudio, ollama, sglang."
    )


def check_llm_health(model: str, timeout_seconds: float = 2.0) -> LLMHealth:
    """Probe the configured local provider without invoking a model."""
    endpoint = resolve_llm_endpoint(model)
    try:
        with httpx.Client(timeout=timeout_seconds) as client:
            response = client.get(endpoint.health_url)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        detail = f"{type(exc).__name__}: {exc}"
        logger.info(
            "LLM provider unavailable: provider=%s health_url=%s detail=%s",
            endpoint.provider,
            endpoint.health_url,
            detail,
        )
        return LLMHealth(endpoint=endpoint, available=False, detail=detail)
    return LLMHealth(endpoint=endpoint, available=True)


def build_llm(model: str, **kwargs: Any) -> BaseChatModel:
    """Return a LangChain chat model for the given ``provider/model-name`` string.

    Extra keyword arguments are forwarded to the underlying model constructor.
    ``None`` values are dropped so optional params (e.g. ``max_tokens=None``)
    don't override server-side defaults.

    If the provider prefix is not recognised (e.g. a bare HuggingFace ``org/model``
    string), the model is routed to LM Studio with the full string as the model id.
    """
    endpoint = resolve_llm_endpoint(model)
    params = {k: v for k, v in kwargs.items() if v is not None}

    if endpoint.provider == "lmstudio":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=endpoint.model_name,
            base_url=endpoint.base_url,
            api_key="lm-studio",
            **params,
        )

    if endpoint.provider == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(
            model=endpoint.model_name,
            base_url=endpoint.base_url,
            **params,
        )

    if endpoint.provider == "sglang":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=endpoint.model_name,
            base_url=endpoint.base_url,
            api_key="none",
            **params,
        )

    raise ValueError(
        f"Unsupported resolved LLM provider '{endpoint.provider}'."
    )
