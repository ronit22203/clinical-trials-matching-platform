"""
server.py — FastAPI reasoning API for the healthcare platform.

Exposes the agentic-reasoning stack over HTTP so platform-ui can call it
without embedding Temporal or LangGraph dependencies in the Next.js process.

Endpoints:
  POST /api/query   — run agent query, return synthesis + execution log
  GET  /api/health  — liveness probe

Start with:
  uvicorn src.server:app --host 0.0.0.0 --port 8000 --reload
  (or: make serve-api in the agentic-reasoning directory)
"""

import logging
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from .config_loader import load_agent_config
from .agent import SimpleAgent

# Lazy-loaded to avoid startup cost when tools aren't configured
try:
    from .tools.registry import ToolRegistry
    _registry_available = True
except ImportError:
    _registry_available = False

logger = logging.getLogger(__name__)

# ── Output sanitization ────────────────────────────────────────────────────────

def _sanitize_output(text: str) -> str:
    """Strip Qwen3 chain-of-thought tags from agent synthesis before returning."""
    text = re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL)
    text = text.replace("<think>", "").replace("</think>", "")
    return text.strip()


# ── Application ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="Healthcare Platform Reasoning API",
    description="Local agentic reasoning over ingested medical documents",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Config resolution ─────────────────────────────────────────────────────────

def _default_agent_config() -> str:
    return "local_assistant"


# ── Request / Response models ─────────────────────────────────────────────────

class CamelModel(BaseModel):
    """Base model that serializes to camelCase JSON (matches TypeScript conventions)."""
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4096)
    tools: list[str] = Field(
        default_factory=list,
        description="Override tool list (empty = use agent config defaults)",
    )
    mode: str = Field(
        default="langgraph",
        pattern="^(langgraph|temporal)$",
    )
    agent_config: str | None = Field(
        default=None,
        description="Path to agent YAML relative to agentic-reasoning root",
    )


class AuditEntry(CamelModel):
    id: str
    step: str
    label: str
    timestamp: str
    duration_ms: int | None = None
    tool_name: str | None = None
    raw_json: dict[str, Any] = Field(default_factory=dict)


class ExecutionLog(CamelModel):
    execution_id: str
    model: str
    latency_ms: float
    tools_called: list[str]
    tokens_input: int
    tokens_output: int
    git_commit: str = "local"
    router_intent: str = "langgraph"
    entries: list[AuditEntry]


class QueryResponse(CamelModel):
    synthesis: str
    execution_log: ExecutionLog
    tool_results: dict[str, str] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    status: str
    version: str = "0.1.0"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_audit_entries(
    execution_id: str,
    query: str,
    metrics: Any,
) -> list[AuditEntry]:
    """Convert ExecutionMetrics into AuditEntry list matching the UI schema."""
    entries: list[AuditEntry] = []
    now = datetime.now(timezone.utc)

    entries.append(AuditEntry(
        id=f"{execution_id}-0",
        step="query_submitted",
        label="Query Submitted",
        timestamp=now.isoformat(),
        raw_json={"query": query, "model": metrics.model},
    ))

    for i, tool_name in enumerate(metrics.tools_called):
        result = metrics.tool_responses.get(tool_name, "")
        entries.append(AuditEntry(
            id=f"{execution_id}-{i + 1}",
            step="tool_called",
            label=tool_name.replace("_", " ").title(),
            timestamp=now.isoformat(),
            tool_name=tool_name,
            raw_json={
                "tool": tool_name,
                "result_length": len(result),
                "result_preview": result[:200] if result else "",
            },
        ))

    entries.append(AuditEntry(
        id=f"{execution_id}-final",
        step="final_decision",
        label="Synthesis Complete",
        timestamp=now.isoformat(),
        duration_ms=int(metrics.latency_ms),
        raw_json={
            "execution_id": execution_id,
            "model": metrics.model,
            "latency_ms": metrics.latency_ms,
            "tokens_input": metrics.tokens_input,
            "tokens_output": metrics.tokens_output,
            "tools_called": metrics.tools_called,
        },
    ))

    return entries


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.post("/api/query", response_model=QueryResponse)
async def query_agent(request: QueryRequest) -> QueryResponse:
    execution_id = str(uuid.uuid4())[:8]

    # Resolve agent config
    try:
        agent_config = load_agent_config(request.agent_config or _default_agent_config())
    except Exception as exc:
        logger.error("Failed to load agent config: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Config load error: {exc}") from exc

    # Override tools if specified in request
    if request.tools:
        from .config_loader import ToolConfig as AgentToolConfig
        agent_config.tools = [AgentToolConfig(name=t) for t in request.tools]

    # Build tool registry
    registry = None
    if _registry_available and agent_config.tools:
        try:
            registry = ToolRegistry.from_agent_config(agent_config)
        except Exception as exc:
            logger.warning("Tool registry init failed (%s) — running without tools", exc)

    agent = SimpleAgent(agent_config, tool_registry=registry)

    try:
        synthesis = _sanitize_output(await agent.run_parallel(request.query))
    except Exception as exc:
        logger.error("Agent execution failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Agent error: {exc}") from exc

    metrics = agent.metrics
    entries = _build_audit_entries(execution_id, request.query, metrics)

    execution_log = ExecutionLog(
        execution_id=execution_id,
        model=metrics.model,
        latency_ms=round(metrics.latency_ms, 1),
        tools_called=metrics.tools_called,
        tokens_input=metrics.tokens_input,
        tokens_output=metrics.tokens_output,
        router_intent=request.mode,
        entries=entries,
    )

    return QueryResponse(
        synthesis=synthesis,
        execution_log=execution_log,
        tool_results=metrics.tool_responses,
    )
