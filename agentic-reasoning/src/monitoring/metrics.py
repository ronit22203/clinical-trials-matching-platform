"""Prometheus metric definitions and helpers for agentic-reasoning."""

from __future__ import annotations

import time

try:
    from prometheus_client import Counter, Histogram
except ImportError:  # pragma: no cover
    Counter = None  # type: ignore[misc, assignment]
    Histogram = None  # type: ignore[misc, assignment]

_LLM_DURATION = (
    Histogram(
        "llm_request_duration_seconds",
        "Wall time for an LLM synthesis invoke or stream",
        ["provider", "model", "mode"],
        buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0),
    )
    if Histogram is not None
    else None
)
_LLM_REQUESTS = (
    Counter(
        "llm_requests_total",
        "LLM synthesis requests",
        ["provider", "model", "status"],
    )
    if Counter is not None
    else None
)
_LLM_TOKENS = (
    Counter(
        "llm_tokens_total",
        "LLM tokens (approximate for streams via completion chunk count)",
        ["provider", "model", "direction"],
    )
    if Counter is not None
    else None
)

_EMBED_QUERY = (
    Histogram(
        "embed_query_duration_seconds",
        "Wall time to embed a retrieval query",
        buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
    )
    if Histogram is not None
    else None
)
_RERANK = (
    Histogram(
        "rerank_duration_seconds",
        "Wall time to rerank retrieval candidates",
        buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    )
    if Histogram is not None
    else None
)
_QDRANT_QUERY = (
    Histogram(
        "qdrant_query_duration_seconds",
        "Wall time for a Qdrant vector query",
        ["collection"],
        buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
    )
    if Histogram is not None
    else None
)
_NEO4J_QUERY = (
    Histogram(
        "neo4j_query_duration_seconds",
        "Wall time for a Neo4j enrichment query",
        buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
    )
    if Histogram is not None
    else None
)


def _split_model(model: str | None) -> tuple[str, str]:
    if not model:
        return "unknown", "unknown"
    provider, _, name = model.partition("/")
    if not name:
        return "unknown", provider
    return provider or "unknown", name or "unknown"


def observe_llm_request(
    *,
    model: str | None,
    duration_seconds: float,
    status: str,
    mode: str = "invoke",
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
) -> None:
    """Record one LLM request outcome."""
    provider, model_name = _split_model(model)
    if _LLM_DURATION is not None:
        _LLM_DURATION.labels(
            provider=provider, model=model_name, mode=mode
        ).observe(duration_seconds)
    if _LLM_REQUESTS is not None:
        _LLM_REQUESTS.labels(
            provider=provider, model=model_name, status=status
        ).inc()
    if _LLM_TOKENS is not None:
        if prompt_tokens:
            _LLM_TOKENS.labels(
                provider=provider, model=model_name, direction="prompt"
            ).inc(prompt_tokens)
        if completion_tokens:
            _LLM_TOKENS.labels(
                provider=provider, model=model_name, direction="completion"
            ).inc(completion_tokens)


def observe_embed_query(duration_seconds: float) -> None:
    if _EMBED_QUERY is not None:
        _EMBED_QUERY.observe(duration_seconds)


def observe_rerank(duration_seconds: float) -> None:
    if _RERANK is not None:
        _RERANK.observe(duration_seconds)


def observe_qdrant_query(*, collection: str, duration_seconds: float) -> None:
    if _QDRANT_QUERY is not None:
        _QDRANT_QUERY.labels(collection=collection or "unknown").observe(
            duration_seconds
        )


def observe_neo4j_query(duration_seconds: float) -> None:
    if _NEO4J_QUERY is not None:
        _NEO4J_QUERY.observe(duration_seconds)


def timed_seconds() -> float:
    return time.perf_counter()
