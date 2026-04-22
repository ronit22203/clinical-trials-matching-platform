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
"""
import os
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel


def build_llm(model: str, **kwargs: Any) -> BaseChatModel:
    """Return a LangChain chat model for the given ``provider/model-name`` string.

    Extra keyword arguments are forwarded to the underlying model constructor.
    ``None`` values are dropped so optional params (e.g. ``max_tokens=None``)
    don't override server-side defaults.
    """
    provider, model_name = model.split("/", 1)
    params = {k: v for k, v in kwargs.items() if v is not None}

    if provider == "lmstudio":
        from langchain_openai import ChatOpenAI
        base_url = os.getenv("LM_STUDIO_BASE_URL", "http://localhost:1234/v1")
        return ChatOpenAI(model=model_name, base_url=base_url, api_key="lm-studio", **params)

    if provider == "ollama":
        from langchain_ollama import ChatOllama
        # LLM_BASE_URL is the canonical name; OLLAMA_BASE_URL kept for backwards compat
        base_url = os.getenv("LLM_BASE_URL") or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        return ChatOllama(model=model_name, base_url=base_url, **params)

    if provider == "sglang":
        from langchain_openai import ChatOpenAI
        base_url = os.getenv("SGLANG_BASE_URL", "http://localhost:30000/v1")
        return ChatOpenAI(model=model_name, base_url=base_url, api_key="none", **params)

    raise ValueError(
        f"Unsupported LLM provider '{provider}' in model string '{model}'. "
        "Supported providers: lmstudio, ollama, sglang."
    )
