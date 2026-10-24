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
import math
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Iterator
from typing import Any, Literal

import httpx
from openai import APIError
from langchain_core.messages import HumanMessage, SystemMessage

from .config import AgentConfig, load_config
from .llm_factory import build_llm, check_llm_health
from .tools.graphrag import GraphRAGTool

logger = logging.getLogger(__name__)

_NO_EVIDENCE_RESPONSE = "No evidence found for this query."
_THINK_BLOCK_RE = re.compile(r"^\s*<think>.*?</think>\s*", re.DOTALL)
_THINK_START = "<think>"
_THINK_END = "</think>"
_TOKEN_ESTIMATE_BYTES_PER_TOKEN = 3
_CHAT_MESSAGE_OVERHEAD_TOKENS = 16
_GRAPH_FACT_TOKEN_CAP = 384
_PROVIDER_ERRORS = (
    APIError,
    httpx.HTTPError,
    ConnectionError,
    TimeoutError,
)


class LLMUnavailableError(RuntimeError):
    """Raised when neither the configured primary nor fallback LLM can serve."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class SynthesisInputTooLargeError(ValueError):
    """Raised when fixed synthesis input leaves no room for grounded evidence."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@dataclass(frozen=True)
class SynthesisResult:
    """A grounded synthesis together with the serving model metadata."""

    text: str
    model: str | None
    fallback_used: bool


@dataclass(frozen=True)
class SynthesisStreamEvent:
    """One token or serving-model change emitted during streamed synthesis."""

    type: Literal["token", "meta"]
    text: str = ""
    model: str | None = None
    fallback_used: bool = False


@dataclass(frozen=True)
class PreparedSynthesisStream:
    """A preflighted synthesis stream ready for HTTP transport."""

    model: str
    fallback_used: bool
    events: Iterator[SynthesisStreamEvent]


@dataclass(frozen=True)
class EvidenceBudgetStats:
    """PHI-safe counts describing the evidence included in an LLM prompt."""

    included_vector_results: int
    omitted_vector_results: int
    included_graph_facts: int
    omitted_graph_facts: int
    content_truncated: bool


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


def _estimate_text_tokens(text: str) -> int:
    """Conservatively estimate local-model tokens without loading a tokenizer."""
    return math.ceil(len(text.encode("utf-8")) / _TOKEN_ESTIMATE_BYTES_PER_TOKEN)


def _estimate_message_tokens(system_content: str, user_content: str) -> int:
    """Estimate two chat messages including template and assistant-prefix overhead."""
    return (
        _estimate_text_tokens(system_content)
        + _estimate_text_tokens(user_content)
        + _CHAT_MESSAGE_OVERHEAD_TOKENS
    )


def _vector_result_block(index: int, hit: dict[str, Any], content: str) -> str:
    source = hit.get("source", "unknown")
    score = hit.get("score", 0)
    chunk_id = hit.get("chunk_id", "unknown")
    return (
        f"[{index}] source={source} chunk_id={chunk_id} score={score:.4f}\n"
        f"{content}"
    )


def _format_evidence(evidence: dict[str, Any]) -> str:
    """Render GraphRAG output as a readable evidence block for the LLM."""
    if not evidence.get("found", False):
        return "No evidence retrieved."

    parts: list[str] = []

    vector_results: list[dict] = evidence.get("vector_results", [])
    for i, hit in enumerate(vector_results, 1):
        content = hit.get("content", "").strip()
        parts.append(_vector_result_block(i, hit, content))

    graph_facts: list[str] = evidence.get("graph_facts", [])
    if graph_facts:
        parts.append("\nKnowledge graph facts:")
        parts.extend(f"  • {fact}" for fact in graph_facts)

    return "\n\n".join(parts) if parts else "No evidence retrieved."


def _format_bounded_evidence(
    evidence: dict[str, Any],
    token_budget: int,
) -> tuple[str, EvidenceBudgetStats]:
    """Fit ranked evidence into a conservative token budget without mutation."""
    vector_results: list[dict[str, Any]] = list(
        evidence.get("vector_results", [])
    )
    graph_facts = [str(fact) for fact in evidence.get("graph_facts", [])]

    included_graph_facts = 0
    graph_lines: list[str] = []
    if graph_facts and token_budget > 0:
        graph_budget = min(
            token_budget,
            _GRAPH_FACT_TOKEN_CAP,
            max(64, token_budget // 5),
        )
        graph_lines = ["Knowledge graph facts:"]
        for fact in graph_facts:
            candidate = "\n".join([*graph_lines, f"- {fact}"])
            if _estimate_text_tokens(candidate) > graph_budget:
                break
            graph_lines.append(f"- {fact}")
            included_graph_facts += 1

        omitted_graph_facts = len(graph_facts) - included_graph_facts
        while omitted_graph_facts:
            omission = (
                f"[{omitted_graph_facts} graph fact(s) omitted to fit context]"
            )
            candidate = "\n".join([*graph_lines, omission])
            if _estimate_text_tokens(candidate) <= graph_budget:
                graph_lines.append(omission)
                break
            if included_graph_facts == 0:
                break
            graph_lines.pop()
            included_graph_facts -= 1
            omitted_graph_facts += 1
        if len(graph_lines) == 1:
            graph_lines = []

    graph_text = "\n".join(graph_lines)
    vector_blocks: list[str] = []
    vector_note = ""
    content_truncated = False

    def render(
        blocks: list[str],
        note: str = "",
    ) -> str:
        parts = [*blocks]
        if note:
            parts.append(note)
        if graph_text:
            parts.append(graph_text)
        return "\n\n".join(parts)

    for index, hit in enumerate(vector_results, 1):
        content = str(hit.get("content", "")).strip()
        full_block = _vector_result_block(index, hit, content)
        if _estimate_text_tokens(render([*vector_blocks, full_block])) <= token_budget:
            vector_blocks.append(full_block)
            continue

        lower_ranked = len(vector_results) - index
        marker = "[content truncated to fit synthesis context"
        if lower_ranked:
            marker += f"; {lower_ranked} lower-ranked hit(s) omitted"
        marker += "]"
        header = _vector_result_block(index, hit, "").rstrip()

        low = 0
        high = len(content)
        best_block = ""
        while low <= high:
            midpoint = (low + high) // 2
            prefix = content[:midpoint].rstrip()
            partial_block = f"{header}\n{prefix}\n{marker}"
            if (
                _estimate_text_tokens(render([*vector_blocks, partial_block]))
                <= token_budget
            ):
                best_block = partial_block
                low = midpoint + 1
            else:
                high = midpoint - 1

        if best_block and high > 0:
            vector_blocks.append(best_block)
            content_truncated = True
        break

    included_vector_results = len(vector_blocks)
    omitted_vector_results = (
        len(vector_results) - included_vector_results
    )
    if omitted_vector_results and not content_truncated:
        candidate_note = (
            f"[{omitted_vector_results} vector hit(s) omitted to fit context]"
        )
        if (
            _estimate_text_tokens(render(vector_blocks, candidate_note))
            <= token_budget
        ):
            vector_note = candidate_note

    formatted = render(vector_blocks, vector_note)
    stats = EvidenceBudgetStats(
        included_vector_results=included_vector_results,
        omitted_vector_results=omitted_vector_results,
        included_graph_facts=included_graph_facts,
        omitted_graph_facts=len(graph_facts) - included_graph_facts,
        content_truncated=content_truncated,
    )
    return formatted, stats


def _strip_reasoning_block(text: str) -> str:
    """Remove a leading local-model reasoning block from a completed response."""
    return _THINK_BLOCK_RE.sub("", text, count=1)


def _visible_stream_tokens(chunks: Iterator[Any]) -> Iterator[str]:
    """Yield answer tokens while suppressing a leading `<think>` block."""
    state: Literal["prefix", "thinking", "answer"] = "prefix"
    buffer = ""
    trim_answer_prefix = False

    for chunk in chunks:
        content = chunk.content or ""
        if not content:
            continue
        token = str(content)

        if state == "answer":
            if trim_answer_prefix:
                token = token.lstrip("\r\n")
                if not token:
                    continue
                trim_answer_prefix = False
            yield token
            continue

        buffer += token
        if state == "prefix":
            candidate = buffer.lstrip()
            if _THINK_START.startswith(candidate) and len(candidate) < len(_THINK_START):
                continue
            if candidate.startswith(_THINK_START):
                state = "thinking"
                buffer = candidate[len(_THINK_START):]
            else:
                state = "answer"
                yield buffer
                buffer = ""
                continue

        end_index = buffer.find(_THINK_END)
        if end_index >= 0:
            state = "answer"
            answer_prefix = buffer[end_index + len(_THINK_END):].lstrip("\r\n")
            buffer = ""
            if answer_prefix:
                trim_answer_prefix = False
                yield answer_prefix
            else:
                trim_answer_prefix = True
        else:
            buffer = buffer[-(len(_THINK_END) - 1):]

    if state == "prefix" and buffer:
        yield buffer
    elif state == "thinking":
        raise LLMUnavailableError(
            "The synthesis model returned an unterminated reasoning block."
        )


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
    def from_config(cls, path: Path | None = None) -> Agent:
        """Construct an Agent from the app.yaml agentic_reasoning section."""
        return cls(load_config(path))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_messages(self, query: str, evidence: dict[str, Any]) -> list[Any]:
        prompt_budget = (
            self.config.context_window_tokens
            - self.config.model_params.max_tokens
            - self.config.prompt_safety_margin_tokens
        )
        user_prefix = f"[QUERY]\n{query}\n\n[EVIDENCE]\n"
        user_suffix = "\n[/EVIDENCE]"
        fixed_user_content = f"{user_prefix}{user_suffix}"
        fixed_tokens = _estimate_message_tokens(
            self.config.system_prompt,
            fixed_user_content,
        )
        evidence_budget = prompt_budget - fixed_tokens
        if evidence_budget <= 0:
            raise SynthesisInputTooLargeError(
                "The system prompt and query exceed the configured synthesis "
                "input budget. Shorten the query and retry."
            )

        context, stats = _format_bounded_evidence(evidence, evidence_budget)
        if (
            not context
            or (
                stats.included_vector_results == 0
                and stats.included_graph_facts == 0
            )
        ):
            raise SynthesisInputTooLargeError(
                "The query leaves insufficient context capacity for retrieved "
                "evidence. Shorten the query and retry."
            )

        user_content = f"{user_prefix}{context}{user_suffix}"
        estimated_tokens = _estimate_message_tokens(
            self.config.system_prompt,
            user_content,
        )
        if estimated_tokens > prompt_budget:
            raise SynthesisInputTooLargeError(
                "The bounded synthesis prompt exceeds the configured input budget."
            )

        logger.info(
            "event=synthesis_prompt_built estimated_tokens=%d prompt_budget=%d "
            "vector_included=%d vector_omitted=%d graph_included=%d "
            "graph_omitted=%d content_truncated=%s",
            estimated_tokens,
            prompt_budget,
            stats.included_vector_results,
            stats.omitted_vector_results,
            stats.included_graph_facts,
            stats.omitted_graph_facts,
            stats.content_truncated,
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

        from .monitoring.metrics import observe_llm_request, timed_seconds

        messages = self._build_messages(query, evidence)
        llm, model, fallback_used = self._select_synthesis_llm()
        started = timed_seconds()
        try:
            response = llm.invoke(messages)
        except _PROVIDER_ERRORS as exc:
            observe_llm_request(
                model=model,
                duration_seconds=timed_seconds() - started,
                status="error",
                mode="invoke",
            )
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
            fallback_started = timed_seconds()
            try:
                response = self.fallback_llm.invoke(messages)
            except _PROVIDER_ERRORS as fallback_exc:
                observe_llm_request(
                    model=fallback_model,
                    duration_seconds=timed_seconds() - fallback_started,
                    status="error",
                    mode="invoke",
                )
                raise LLMUnavailableError(
                    f"Synthesis invocation failed for fallback {fallback_model}: "
                    f"{type(fallback_exc).__name__}: {fallback_exc}"
                ) from fallback_exc
            fallback_text = _strip_reasoning_block(str(response.content or "")).strip()
            observe_llm_request(
                model=fallback_model,
                duration_seconds=timed_seconds() - fallback_started,
                status="ok",
                mode="invoke",
                completion_tokens=max(1, len(fallback_text) // _TOKEN_ESTIMATE_BYTES_PER_TOKEN),
            )
            return SynthesisResult(
                text=fallback_text or _NO_EVIDENCE_RESPONSE,
                model=fallback_model,
                fallback_used=True,
            )

        response_text = _strip_reasoning_block(str(response.content or "")).strip()
        observe_llm_request(
            model=model,
            duration_seconds=timed_seconds() - started,
            status="ok",
            mode="invoke",
            completion_tokens=max(1, len(response_text) // _TOKEN_ESTIMATE_BYTES_PER_TOKEN),
        )
        return SynthesisResult(
            text=response_text or _NO_EVIDENCE_RESPONSE,
            model=model,
            fallback_used=fallback_used,
        )

    def _stream_synthesis_events(
        self,
        messages: list[Any],
        llm: Any,
        model: str,
        fallback_used: bool,
    ) -> Iterator[SynthesisStreamEvent]:
        from .monitoring.metrics import observe_llm_request, timed_seconds

        emitted_token = False
        completion_chars = 0
        started = timed_seconds()
        try:
            for token in _visible_stream_tokens(llm.stream(messages)):
                emitted_token = True
                completion_chars += len(token)
                yield SynthesisStreamEvent(type="token", text=token)
            observe_llm_request(
                model=model,
                duration_seconds=timed_seconds() - started,
                status="ok",
                mode="stream",
                completion_tokens=max(
                    1, completion_chars // _TOKEN_ESTIMATE_BYTES_PER_TOKEN
                ),
            )
            return
        except _PROVIDER_ERRORS as exc:
            observe_llm_request(
                model=model,
                duration_seconds=timed_seconds() - started,
                status="error",
                mode="stream",
            )
            fallback_model = self.config.fallback_model
            if (
                emitted_token
                or fallback_used
                or not fallback_model
                or self.fallback_llm is None
            ):
                raise LLMUnavailableError(
                    f"Synthesis stream failed for {model}: {type(exc).__name__}: {exc}"
                ) from exc

            fallback_health = check_llm_health(
                fallback_model,
                self.config.health_check_timeout_seconds,
            )
            if not fallback_health.available:
                raise LLMUnavailableError(
                    "Synthesis stream is unavailable after primary transport failure: "
                    f"primary ({model}) error={type(exc).__name__}: {exc}; "
                    f"fallback ({fallback_model}) health check failed: {fallback_health.detail}"
                ) from exc

            logger.warning(
                "Primary synthesis stream failed before output; switching fallback: "
                "primary=%s fallback=%s error=%s",
                model,
                fallback_model,
                type(exc).__name__,
            )
            yield SynthesisStreamEvent(
                type="meta",
                model=fallback_model,
                fallback_used=True,
            )

            fallback_started = timed_seconds()
            fallback_chars = 0
            try:
                for token in _visible_stream_tokens(self.fallback_llm.stream(messages)):
                    fallback_chars += len(token)
                    yield SynthesisStreamEvent(type="token", text=token)
                observe_llm_request(
                    model=fallback_model,
                    duration_seconds=timed_seconds() - fallback_started,
                    status="ok",
                    mode="stream",
                    completion_tokens=max(
                        1, fallback_chars // _TOKEN_ESTIMATE_BYTES_PER_TOKEN
                    ),
                )
            except _PROVIDER_ERRORS as fallback_exc:
                observe_llm_request(
                    model=fallback_model,
                    duration_seconds=timed_seconds() - fallback_started,
                    status="error",
                    mode="stream",
                )
                raise LLMUnavailableError(
                    f"Synthesis stream failed for fallback {fallback_model}: "
                    f"{type(fallback_exc).__name__}: {fallback_exc}"
                ) from fallback_exc

    def prepare_synthesis_stream(
        self,
        query: str,
        evidence: dict[str, Any],
    ) -> PreparedSynthesisStream:
        """Preflight a grounded stream without repeating evidence retrieval."""
        if not evidence.get("found", False):
            raise ValueError("Cannot stream synthesis without retrieved evidence.")

        messages = self._build_messages(query, evidence)
        llm, model, fallback_used = self._select_synthesis_llm()
        return PreparedSynthesisStream(
            model=model,
            fallback_used=fallback_used,
            events=self._stream_synthesis_events(
                messages,
                llm,
                model,
                fallback_used,
            ),
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

        logger.info("Phase 2 — streaming synthesis")
        prepared = self.prepare_synthesis_stream(query, evidence)
        for event in prepared.events:
            if event.type == "token":
                yield event.text

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
