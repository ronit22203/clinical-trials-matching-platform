"""
Two-phase clinical research agent.

Phase 1 — Mandatory tool execution (no LLM routing decision):
    GraphRAG is called directly and always runs before the LLM sees the query.

Phase 2 — Evidence-grounded synthesis:
    The LLM receives only the retrieved evidence + query. A strict system prompt
    prevents parametric memory use. If GraphRAG returns found=false, the LLM
    responds with a fixed "no evidence" message — no speculation.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

import httpx
from openai import APIConnectionError, APITimeoutError
from langchain_core.messages import HumanMessage, SystemMessage

from .config import AgentConfig, load_config
from .llm_factory import build_llm, check_llm_health
from .tools.graphrag import GraphRAGTool

logger = logging.getLogger(__name__)

_NO_EVIDENCE_RESPONSE = "No evidence found for this query."


class LLMUnavailableError(RuntimeError):
    """Raised when neither the configured primary nor fallback LLM can serve."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@dataclass(frozen=True)
class SynthesisResult:
    """A grounded synthesis together with the serving model metadata."""

    text: str
    model: str | None
    fallback_used: bool


@dataclass
class RunResult:
    query: str
    evidence: dict[str, Any]
    synthesis: str
    latency_ms: float
    synthesis_model: str | None = None
    fallback_used: bool = False
    found: bool = field(init=False)

    def __post_init__(self) -> None:
        self.found = bool(self.evidence.get("found", False))


def _format_evidence(evidence: dict[str, Any]) -> str:
    """Render GraphRAG output as a readable evidence block for the LLM."""
    if not evidence.get("found", False):
        return "No evidence retrieved."

    parts: list[str] = []

    vector_results: list[dict] = evidence.get("vector_results", [])
    for i, hit in enumerate(vector_results, 1):
        source = hit.get("source", "unknown")
        score = hit.get("score", 0)
        content = hit.get("content", "").strip()
        parts.append(f"[{i}] source={source} score={score:.4f}\n{content}")

    graph_facts: list[str] = evidence.get("graph_facts", [])
    if graph_facts:
        parts.append("\nKnowledge graph facts:")
        parts.extend(f"  • {fact}" for fact in graph_facts)

    return "\n\n".join(parts) if parts else "No evidence retrieved."


class Agent:
    """Deterministic two-phase pipeline: GraphRAG retrieval → grounded synthesis."""

    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        params = config.model_params.model_dump(exclude_none=True)
        self.llm = build_llm(config.model, **params)
        self.fallback_llm = (
            build_llm(config.fallback_model, **params)
            if config.fallback_model
            else None
        )
        self.graphrag = GraphRAGTool(config.graphrag.model_dump())

    @classmethod
    def from_config(cls, path: Path | None = None) -> "Agent":
        """Construct an Agent from the app.yaml agentic_reasoning section."""
        return cls(load_config(path))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_messages(self, query: str, evidence: dict[str, Any]) -> list:
        context = _format_evidence(evidence)
        user_content = (
            f"[QUERY]\n{query}\n\n"
            f"[EVIDENCE]\n{context}\n[/EVIDENCE]"
        )
        return [
            SystemMessage(content=self.config.system_prompt),
            HumanMessage(content=user_content),
        ]

    def _select_synthesis_llm(self) -> tuple[Any, str, bool]:
        """Return a healthy primary model or an explicitly configured fallback."""
        timeout = self.config.health_check_timeout_seconds
        primary_health = check_llm_health(self.config.model, timeout)
        if primary_health.available:
            return self.llm, self.config.model, False

        fallback_model = self.config.fallback_model
        if fallback_model and self.fallback_llm is not None:
            fallback_health = check_llm_health(fallback_model, timeout)
            if fallback_health.available:
                logger.warning(
                    "Primary LLM unavailable; using configured fallback: primary=%s fallback=%s",
                    self.config.model,
                    fallback_model,
                )
                return self.fallback_llm, fallback_model, True
            raise LLMUnavailableError(
                "Synthesis is unavailable: "
                f"primary ({self.config.model}) health check failed: {primary_health.detail}; "
                f"fallback ({fallback_model}) health check failed: {fallback_health.detail}"
            )

        raise LLMUnavailableError(
            "Synthesis is unavailable: "
            f"primary ({self.config.model}) health check failed: {primary_health.detail}; "
            "no fallback model is configured."
        )

    def synthesize(self, query: str, evidence: dict[str, Any]) -> SynthesisResult:
        """Produce a strictly evidence-grounded synthesis with explicit failover."""
        if not evidence.get("found", False):
            return SynthesisResult(
                text=_NO_EVIDENCE_RESPONSE,
                model=None,
                fallback_used=False,
            )

        messages = self._build_messages(query, evidence)
        llm, model, fallback_used = self._select_synthesis_llm()
        try:
            response = llm.invoke(messages)
        except (APIConnectionError, APITimeoutError, httpx.HTTPError, ConnectionError, TimeoutError) as exc:
            if fallback_used or not self.config.fallback_model or self.fallback_llm is None:
                raise LLMUnavailableError(
                    f"Synthesis invocation failed for {model}: {type(exc).__name__}: {exc}"
                ) from exc

            fallback_model = self.config.fallback_model
            fallback_health = check_llm_health(
                fallback_model,
                self.config.health_check_timeout_seconds,
            )
            if not fallback_health.available:
                raise LLMUnavailableError(
                    "Synthesis is unavailable after primary invocation failed: "
                    f"primary ({model}) error={type(exc).__name__}: {exc}; "
                    f"fallback ({fallback_model}) health check failed: {fallback_health.detail}"
                ) from exc

            logger.warning(
                "Primary LLM invocation failed; retrying configured fallback: "
                "primary=%s fallback=%s error=%s",
                model,
                fallback_model,
                type(exc).__name__,
            )
            try:
                response = self.fallback_llm.invoke(messages)
            except (APIConnectionError, APITimeoutError, httpx.HTTPError, ConnectionError, TimeoutError) as fallback_exc:
                raise LLMUnavailableError(
                    f"Synthesis invocation failed for fallback {fallback_model}: "
                    f"{type(fallback_exc).__name__}: {fallback_exc}"
                ) from fallback_exc
            return SynthesisResult(
                text=response.content or _NO_EVIDENCE_RESPONSE,
                model=fallback_model,
                fallback_used=True,
            )

        return SynthesisResult(
            text=response.content or _NO_EVIDENCE_RESPONSE,
            model=model,
            fallback_used=fallback_used,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, query: str) -> RunResult:
        """Blocking two-phase run. Returns a RunResult with synthesis and evidence."""
        t0 = time.perf_counter()

        # Phase 1: deterministic tool execution
        logger.info("Phase 1 — GraphRAG retrieval for query: %s", query)
        evidence = self.graphrag.cached_execute(query)
        if not isinstance(evidence, dict):
            evidence = {"found": False, "error": str(evidence)}
        logger.info(
            "Phase 1 complete — found=%s, vector_hits=%d, graph_facts=%d",
            evidence.get("found"),
            len(evidence.get("vector_results", [])),
            len(evidence.get("graph_facts", [])),
        )

        # Phase 2: grounded synthesis
        logger.info("Phase 2 — LLM synthesis from evidence")
        synthesis_result = self.synthesize(query, evidence)

        latency_ms = (time.perf_counter() - t0) * 1000
        logger.info("Run complete in %.0fms", latency_ms)

        return RunResult(
            query=query,
            evidence=evidence,
            synthesis=synthesis_result.text,
            latency_ms=latency_ms,
            synthesis_model=synthesis_result.model,
            fallback_used=synthesis_result.fallback_used,
        )

    def stream(self, query: str) -> Iterator[str]:
        """Two-phase streaming run. Phase 1 blocks; Phase 2 streams synthesis tokens.

        Yields string chunks as they arrive. Callers can accumulate them to reconstruct
        the full synthesis. Evidence is retrievable via agent.last_evidence after the
        generator is exhausted.
        """
        # Phase 1: blocking (must complete before LLM sees anything)
        logger.info("Phase 1 — GraphRAG retrieval (stream mode)")
        evidence = self.graphrag.cached_execute(query)
        if not isinstance(evidence, dict):
            evidence = {"found": False, "error": str(evidence)}
        self.last_evidence = evidence

        logger.info(
            "Phase 1 complete — found=%s, vector_hits=%d",
            evidence.get("found"),
            len(evidence.get("vector_results", [])),
        )

        if not evidence.get("found", False):
            yield _NO_EVIDENCE_RESPONSE
            return

        # Phase 2: stream synthesis tokens. The selected provider is checked
        # before streaming so an unavailable primary can use the fallback.
        logger.info("Phase 2 — streaming synthesis")
        messages = self._build_messages(query, evidence)
        llm, _, _ = self._select_synthesis_llm()
        for chunk in llm.stream(messages):
            token = chunk.content or ""
            if token:
                yield token

    def run_json(self, query: str) -> dict[str, Any]:
        """Run and return a JSON-serialisable dict (for server/CLI use)."""
        result = self.run(query)
        return {
            "query": result.query,
            "synthesis": result.synthesis,
            "found": result.found,
            "synthesis_model": result.synthesis_model,
            "fallback_used": result.fallback_used,
            "latency_ms": round(result.latency_ms, 1),
            "evidence": result.evidence,
        }
