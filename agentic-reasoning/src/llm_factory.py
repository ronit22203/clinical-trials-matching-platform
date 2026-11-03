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
import json
import logging
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

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
        if self.provider == "lmstudio":
            parsed = urlsplit(self.base_url)
            return urlunsplit(
                (parsed.scheme, parsed.netloc, "/api/v1/models", "", "")
            )
        return f"{self.base_url.rstrip('/')}/models"


@dataclass(frozen=True)
class LLMHealth:
    """Availability result for a local LLM provider."""

    endpoint: LLMEndpoint
    available: bool
    detail: str | None = None


def _usable_model_names(
    endpoint: LLMEndpoint, payload: object
) -> tuple[str, ...] | None:
    """Extract usable model identifiers, or return ``None`` for bad schemas."""
    if not isinstance(payload, dict):
        return None

    if endpoint.provider == "ollama":
        entries = payload.get("models")
        identifier_fields = ("name", "model")
    elif endpoint.provider == "lmstudio":
        entries = payload.get("models")
        if not isinstance(entries, list):
            return None
        names: list[str] = []
        valid_entries = 0
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            loaded_instances = entry.get("loaded_instances")
            key = entry.get("key")
            publisher = entry.get("publisher")
            if not isinstance(loaded_instances, list) or not isinstance(key, str):
                continue
            valid_entries += 1
            if loaded_instances and key.strip():
                if isinstance(publisher, str) and publisher.strip():
                    names.append(f"{publisher.strip()}/{key.strip()}")
                else:
                    names.append(key.strip())
                names.extend(
                    instance_id.strip()
                    for instance in loaded_instances
                    if isinstance(instance, dict)
                    and isinstance((instance_id := instance.get("id")), str)
                    and instance_id.strip()
                )
        if entries and valid_entries == 0:
            return None
        return tuple(names)
    else:
        entries = payload.get("data")
        identifier_fields = ("id",)

    if not isinstance(entries, list):
        return None

    names: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        for field in identifier_fields:
            value = entry.get(field)
            if isinstance(value, str) and value.strip():
                names.append(value.strip())
                break

    if entries and not names:
        return None
    return tuple(names)


def _normalize_model_id(model: str) -> str:
    """Normalize one provider model identifier for exact comparison."""
    return model.strip().casefold().rstrip("/").removesuffix(":latest")


def _model_ids_match(configured: str, available: str) -> bool:
    """Match exact IDs, allowing basename aliases only when one ID is unqualified."""
    configured_id = _normalize_model_id(configured)
    available_id = _normalize_model_id(available)
    if not configured_id or not available_id:
        return False
    if configured_id == available_id:
        return True
    if "/" in configured_id and "/" in available_id:
        return False
    return configured_id.rsplit("/", 1)[-1] == available_id.rsplit("/", 1)[-1]


def _configured_model_is_available(
    endpoint: LLMEndpoint,
    model_names: tuple[str, ...],
) -> bool:
    return any(_model_ids_match(endpoint.model_name, name) for name in model_names)


def _unavailable_health(endpoint: LLMEndpoint, detail: str) -> LLMHealth:
    """Build and log an unavailable health result without response payload data."""
    logger.info(
        "LLM provider unavailable: provider=%s health_url=%s detail=%s",
        endpoint.provider,
        endpoint.health_url,
        detail,
    )
    return LLMHealth(endpoint=endpoint, available=False, detail=detail)


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
    """Probe the provider's model listing without invoking a model."""
    endpoint = resolve_llm_endpoint(model)
    try:
        with httpx.Client(timeout=timeout_seconds) as client:
            response = client.get(endpoint.health_url)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        detail = f"{type(exc).__name__}: {exc}"
        return _unavailable_health(endpoint, detail)

    try:
        payload = response.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _unavailable_health(
            endpoint,
            "Malformed model-list response: expected JSON; verify the provider API.",
        )

    model_names = _usable_model_names(endpoint, payload)
    if model_names is None:
        expected = {
            "ollama": "{models: [{name or model: ...}]}",
            "lmstudio": "{models: [{key: ..., loaded_instances: [...]}]}",
        }.get(endpoint.provider, "{data: [{id: ...}]}")
        return _unavailable_health(
            endpoint,
            f"Malformed model-list response: expected {expected}; "
            "verify the provider API.",
        )

    if not model_names:
        action = (
            "pull or configure a model in Ollama"
            if endpoint.provider == "ollama"
            else f"load the configured model in {endpoint.provider}"
        )
        return _unavailable_health(
            endpoint,
            f"No usable models are available; {action} and retry.",
        )

    if not _configured_model_is_available(endpoint, model_names):
        return _unavailable_health(
            endpoint,
            f"Configured model is not available: {endpoint.model_name}.",
        )

    return LLMHealth(endpoint=endpoint, available=True)


def _ollama_params(params: dict[str, Any]) -> dict[str, Any]:
    """Map the shared model params onto fields ChatOllama actually applies.

    ChatOllama caps generation with ``num_predict``. The shared config name is
    ``max_tokens``, and Pydantic drops that unknown field, which leaves Ollama
    generating until the context window fills.
    """
    translated = dict(params)
    max_tokens = translated.pop("max_tokens", None)
    translated.pop("frequency_penalty", None)
    translated.pop("presence_penalty", None)
    if translated.get("num_predict") is None and max_tokens is not None:
        translated["num_predict"] = max_tokens
    return {k: v for k, v in translated.items() if v is not None}


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
            **_ollama_params(params),
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
