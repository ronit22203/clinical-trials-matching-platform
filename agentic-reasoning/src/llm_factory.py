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
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel

logger = logging.getLogger(__name__)

_KNOWN_PROVIDERS = {"lmstudio", "ollama", "sglang"}


def build_llm(model: str, **kwargs: Any) -> BaseChatModel:
    """Return a LangChain chat model for the given ``provider/model-name`` string.

    Extra keyword arguments are forwarded to the underlying model constructor.
    ``None`` values are dropped so optional params (e.g. ``max_tokens=None``)
    don't override server-side defaults.

    If the provider prefix is not recognised (e.g. a bare HuggingFace ``org/model``
    string), the model is routed to LM Studio with the full string as the model id.
    """
    parts = model.split("/", 1)
    provider = parts[0] if len(parts) > 1 else ""
    params = {k: v for k, v in kwargs.items() if v is not None}

    if provider == "lmstudio":
        model_name = parts[1]
        from langchain_openai import ChatOpenAI
        base_url = os.getenv("LM_STUDIO_BASE_URL", "http://localhost:1234/v1")
        return ChatOpenAI(model=model_name, base_url=base_url, api_key="lm-studio", **params)

    if provider == "ollama":
        model_name = parts[1]
        from langchain_ollama import ChatOllama
        # LLM_BASE_URL is the canonical name; OLLAMA_BASE_URL kept for backwards compat
        base_url = os.getenv("LLM_BASE_URL") or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        return ChatOllama(model=model_name, base_url=base_url, **params)

    if provider == "sglang":
        model_name = parts[1]
        from langchain_openai import ChatOpenAI
        base_url = os.getenv("SGLANG_BASE_URL", "http://localhost:30000/v1")
        return ChatOpenAI(model=model_name, base_url=base_url, api_key="none", **params)

    # Unknown prefix — assume the full string is a HuggingFace-style model identifier
    # being served by LM Studio (e.g. "mradermacher/Llama-3.1-8B-UltraMedical-GGUF").
    # LM Studio uses the full org/model string as the model id in its OpenAI-compatible API.
    if provider and provider not in _KNOWN_PROVIDERS:
        logger.warning(
            "Unknown provider prefix '%s' in model string '%s'. "
            "Routing to LM Studio with the full model identifier. "
            "Set LM_STUDIO_BASE_URL to override the server endpoint.",
            provider, model,
        )
        from langchain_openai import ChatOpenAI
        base_url = os.getenv("LM_STUDIO_BASE_URL", "http://localhost:1234/v1")
        return ChatOpenAI(model=model, base_url=base_url, api_key="lm-studio", **params)

    raise ValueError(
        f"Unsupported LLM provider '{provider}' in model string '{model}'. "
        "Supported providers: lmstudio, ollama, sglang. "
        "For HuggingFace GGUF models served via LM Studio, pass the full "
        "'org/model' string directly (e.g. 'mradermacher/Llama-3.1-8B-UltraMedical-GGUF')."
    )
