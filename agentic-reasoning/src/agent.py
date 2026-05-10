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

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from langchain_core.messages import HumanMessage, SystemMessage

from .config import AgentConfig, load_config
from .llm_factory import build_llm
from .tools.graphrag import GraphRAGTool

logger = logging.getLogger(__name__)

_NO_EVIDENCE_RESPONSE = "No evidence found for this query."


@dataclass
class RunResult:
    query: str
    evidence: dict[str, Any]
    synthesis: str
    latency_ms: float
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
        score = hit.get("reranker_score") or hit.get("score", 0)
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
        if not evidence.get("found", False):
            synthesis = _NO_EVIDENCE_RESPONSE
        else:
            logger.info("Phase 2 — LLM synthesis from evidence")
            messages = self._build_messages(query, evidence)
            response = self.llm.invoke(messages)
            synthesis = response.content

        latency_ms = (time.perf_counter() - t0) * 1000
        logger.info("Run complete in %.0fms", latency_ms)

        return RunResult(
            query=query,
            evidence=evidence,
            synthesis=synthesis,
            latency_ms=latency_ms,
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

        # Phase 2: stream synthesis tokens
        logger.info("Phase 2 — streaming synthesis")
        messages = self._build_messages(query, evidence)
        for chunk in self.llm.stream(messages):
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
            "latency_ms": round(result.latency_ms, 1),
            "evidence": result.evidence,
        }
