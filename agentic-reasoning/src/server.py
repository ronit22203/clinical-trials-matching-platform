"""
FastAPI reasoning server — serves the clinical-match simple-ui on :8000.

Endpoints
---------
POST /api/match          — Phase 1: hybrid GraphRAG retrieval → matches JSON
GET  /api/verify         — Snippet by byte range from clean artifact
GET  /api/stats          — Latest benchmark run summary
GET  /api/pdf/{doi_path} — Stream a raw PDF file
GET  /api/debug/heatmap  — Sentence-level cosine similarity heatmap
GET  /api/debug/subgraph — 1-hop Neo4j neighbourhood (D3 force graph)
POST /api/synthesis      — Phase 2: LLM synthesis from cached evidence
POST /api/synthesis/stream — Phase 2: token-streamed synthesis from cached evidence
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]

# ── Auth ──────────────────────────────────────────────────────────────────────

from .auth import create_access_token, verify_password, verify_token  # noqa: E402
from .config import _load_dotenv  # noqa: E402

# Load .env.local at startup so AUTH_* vars are available before any request.
_load_dotenv()

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="Clinical Agents Reasoning API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Agent singleton (lazy-init, expensive models load once) ───────────────────

_agent: Any = None
_agent_init_lock = asyncio.Lock()
_agent_warmup_task: asyncio.Task[Any] | None = None


async def _get_agent() -> Any:
    global _agent
    if _agent is None:
        async with _agent_init_lock:
            if _agent is None:
                from .agent import Agent

                loop = asyncio.get_event_loop()
                logger.info("Initialising Agent and retrieval models…")
                agent = await loop.run_in_executor(None, Agent.from_config)
                await loop.run_in_executor(None, agent.graphrag.warmup)
                _agent = agent
                logger.info("Agent and retrieval models ready.")
    return _agent


def _start_agent_warmup() -> None:
    """Start one background warm-up after login so queries avoid cold starts."""
    global _agent_warmup_task
    if _agent is not None:
        return
    if _agent_warmup_task is not None and not _agent_warmup_task.done():
        return

    _agent_warmup_task = asyncio.create_task(_get_agent())

    def _consume_result(task: asyncio.Task[Any]) -> None:
        try:
            task.result()
        except asyncio.CancelledError:
            logger.info("Agent warm-up cancelled")
        except Exception:
            logger.exception("Agent warm-up failed; the next query will retry")

    _agent_warmup_task.add_done_callback(_consume_result)


# ── Evidence cache: opaque IDs prevent cross-context synthesis reuse ──────────

_evidence_cache: OrderedDict[str, dict] = OrderedDict()
_CACHE_MAX = 32


def _cache_put(query: str, evidence: dict) -> str:
    evidence_id = uuid4().hex
    _evidence_cache[evidence_id] = {
        "query": query,
        "evidence": evidence,
    }
    if len(_evidence_cache) > _CACHE_MAX:
        _evidence_cache.popitem(last=False)
    return evidence_id


def _cache_get(evidence_id: str) -> dict | None:
    return _evidence_cache.get(evidence_id)


# ── Helpers ───────────────────────────────────────────────────────────────────

_GRAPH_FACT_RE = re.compile(r"^(.+?)\s+--\[(.+?)\]-->\s+(.+)$")


def _parse_graph_fact(fact: str) -> dict | None:
    m = _GRAPH_FACT_RE.match(fact.strip())
    if not m:
        return None
    return {"head": m.group(1).strip(), "relation": m.group(2).strip(), "tail": m.group(3).strip()}


def _graphrag_to_matches(evidence: dict) -> list[dict]:
    """Convert GraphRAG output to the matches array the UI expects."""
    vector_results: list[dict] = evidence.get("vector_results", [])
    graph_facts: list[str] = evidence.get("graph_facts", [])

    parsed_facts = [p for f in graph_facts if (p := _parse_graph_fact(f))]

    matches = []
    for i, hit in enumerate(vector_results):
        source = hit.get("source", "")
        # attach graph facts to the first chunk that shares the same source,
        # otherwise leave evidence empty — the UI still shows graph triples
        evidence_entries = []
        if i == 0 and parsed_facts:
            evidence_entries = [
                {
                    "head": f["head"],
                    "relation": f["relation"],
                    "tail": f["tail"],
                    "tier": 1,
                    "source": source,
                    "byteStart": 0,
                    "byteEnd": 0,
                }
                for f in parsed_facts[:10]
            ]
        matches.append(
            {
                "chunkIndex": hit.get("chunk_index", i),
                "score": hit.get("score", 0),
                "rankScore": hit.get("reranker_score"),
                "collection": hit.get("collection"),
                "scope": hit.get("scope"),
                "source": source,
                "content": hit.get("content", ""),
                "context": hit.get("context") or "",
                "pageNumber": hit.get("page_number"),
                "charStart": hit.get("char_start"),
                "charEnd": hit.get("char_end"),
                "evidence": evidence_entries,
            }
        )
    return matches


# ── Routes ────────────────────────────────────────────────────────────────────


@app.post("/api/auth/login")
async def login(form: OAuth2PasswordRequestForm = Depends()) -> JSONResponse:
    """Issue a JWT access token for valid username/password credentials."""
    import os

    expected_user = os.environ.get("AUTH_USERNAME", "").strip()
    expected_hash = os.environ.get("AUTH_PASSWORD_HASH", "").strip()

    if not expected_user or not expected_hash.startswith("$2"):
        logger.error("AUTH_USERNAME or AUTH_PASSWORD_HASH not configured")
        raise HTTPException(
            status_code=503,
            detail={
                "code": "auth_not_configured",
                "message": "Authentication is not configured on this server. "
                "Set AUTH_PASSWORD_HASH (bcrypt) and AUTH_JWT_SECRET in .env.local.",
                "retryable": False,
            },
        )

    if form.username != expected_user or not verify_password(form.password, expected_hash):
        raise HTTPException(
            status_code=401,
            detail={
                "code": "invalid_credentials",
                "message": "Incorrect username or password.",
                "retryable": False,
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(sub=form.username)
    logger.info("Successful login for user=%s", form.username)
    _start_agent_warmup()
    return JSONResponse({"access_token": token, "token_type": "bearer"})


@app.post("/api/match")
async def match(
    query: str = Form(...),
    target: Literal["literature", "patient_context"] = Form(default="literature"),
    source: str | None = Form(default=None),
    source_slug: str | None = Form(default=None),
    top_k: int = Form(default=10, ge=1, le=50),
    file: UploadFile | None = File(default=None),
    _user: str = Depends(verify_token),
) -> JSONResponse:
    """Phase 1 — GraphRAG hybrid retrieval. Returns matches for the UI."""
    if target == "patient_context" and not source:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "source_required",
                "message": "Patient-context retrieval requires an active document.",
                "retryable": False,
            },
        )
    if target == "literature" and (source or source_slug):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_retrieval_context",
                "message": "Literature retrieval cannot include a patient source.",
                "retryable": False,
            },
        )

    agent = await _get_agent()
    t0 = time.perf_counter()
    retrieval_request = {
        "query": query,
        "target": target,
        "source": source,
        "source_slug": source_slug,
        "limit": top_k,
    }

    loop = asyncio.get_event_loop()
    from .tools.graphrag import GraphRAGUnavailableError

    try:
        evidence = await loop.run_in_executor(
            None,
            agent.graphrag.cached_execute,
            retrieval_request,
        )
    except GraphRAGUnavailableError as exc:
        logger.error(
            "Retrieval unavailable: target=%s error=%s",
            target,
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=503,
            detail={
                "code": "retrieval_unavailable",
                "message": str(exc),
                "retryable": True,
            },
        ) from exc
    if not isinstance(evidence, dict):
        raise HTTPException(
            status_code=500,
            detail={
                "code": "invalid_retrieval_response",
                "message": str(evidence),
                "retryable": False,
            },
        )

    latency_ms = round((time.perf_counter() - t0) * 1000, 1)
    matches = _graphrag_to_matches(evidence) if evidence.get("found") else []
    evidence_id = _cache_put(query, evidence) if evidence.get("found") else None

    return JSONResponse(
        {
            "query": query,
            "found": evidence.get("found", False),
            "matches": matches,
            "graphFacts": evidence.get("graph_facts", []),
            "graphAnchor": evidence.get("graph_anchor"),
            "retrievalContext": evidence.get("retrieval_context"),
            "empty": evidence.get("empty"),
            "evidenceId": evidence_id,
            "latency_ms": latency_ms,
        }
    )


@app.get("/api/verify")
async def verify(source: str, byte_start: int = 0, byte_end: int = 512, _user: str = Depends(verify_token)) -> JSONResponse:
    """Return a text snippet from a clean-artifact file by byte range."""
    # source may be a bare filename or a relative path — resolve under repo root
    candidate = _REPO_ROOT / source
    if not candidate.exists():
        # try scanning clean artifacts
        for p in (_REPO_ROOT / "data" / "artifacts" / "clean").rglob("*"):
            if p.name == Path(source).name and p.suffix in {".md", ".txt"}:
                candidate = p
                break

    if not candidate.exists():
        raise HTTPException(status_code=404, detail=f"Source not found: {source}")

    data = candidate.read_bytes()
    snippet = data[byte_start:byte_end].decode("utf-8", errors="replace")
    return JSONResponse({"source": source, "snippet": snippet, "byte_start": byte_start, "byte_end": byte_end})


@app.get("/api/stats")
async def stats(_user: str = Depends(verify_token)) -> JSONResponse:
    """Return latest benchmark run summary from benchmarking/results/."""
    results_dir = _REPO_ROOT / "benchmarking" / "results"
    if not results_dir.exists():
        return JSONResponse(None)

    runs = sorted(
        (p for p in results_dir.iterdir() if p.is_dir()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for run in runs:
        manifest = run / "manifest.json"
        if manifest.exists():
            try:
                return JSONResponse(json.loads(manifest.read_text()))
            except Exception:
                pass
        report = run / "retrieval.json"
        if report.exists():
            try:
                return JSONResponse({"run_id": run.name, **json.loads(report.read_text())})
            except Exception:
                pass
    return JSONResponse(None)


@app.get("/api/health")
async def health() -> JSONResponse:
    """Report synthesis-provider readiness without loading retrieval clients."""
    from pydantic import ValidationError

    from .config import load_config
    from .llm_factory import check_llm_health

    try:
        config = load_config()
    except ValidationError as exc:
        logger.error("Reasoning configuration is invalid: %s", exc)
        return JSONResponse(
            status_code=503,
            content={
                "status": "unavailable",
                "synthesis": {
                    "primary": None,
                    "fallback": None,
                    "detail": "Reasoning configuration is invalid.",
                },
            },
        )

    loop = asyncio.get_running_loop()

    def _probe() -> tuple[Any, Any | None]:
        primary = check_llm_health(
            config.model,
            config.health_check_timeout_seconds,
        )
        fallback = (
            check_llm_health(
                config.fallback_model,
                config.health_check_timeout_seconds,
            )
            if config.fallback_model
            else None
        )
        return primary, fallback

    primary, fallback = await loop.run_in_executor(None, _probe)
    active_model = (
        config.model
        if primary.available
        else config.fallback_model
        if fallback and fallback.available
        else None
    )
    status = "ready" if primary.available else "degraded" if active_model else "unavailable"
    status_code = 200 if active_model else 503
    return JSONResponse(
        status_code=status_code,
        content={
            "status": status,
            "synthesis": {
                "primary": {
                    "model": config.model,
                    "available": primary.available,
                    "detail": primary.detail,
                },
                "fallback": (
                    {
                        "model": config.fallback_model,
                        "available": fallback.available,
                        "detail": fallback.detail,
                    }
                    if fallback
                    else None
                ),
                "active_model": active_model,
            },
        },
    )


@app.get("/api/pdf/{doi_path:path}")
async def serve_pdf(doi_path: str, _user: str = Depends(verify_token)) -> FileResponse:
    """Stream a PDF from data/pdfs/raw/."""
    base = _REPO_ROOT / "data" / "pdfs"
    # try exact path first, then scan by filename
    candidate = base / "raw" / doi_path
    if not candidate.exists():
        name = Path(doi_path).name
        for p in base.rglob("*.pdf"):
            if p.name == name or doi_path in str(p):
                candidate = p
                break

    if not candidate.exists():
        raise HTTPException(status_code=404, detail=f"PDF not found: {doi_path}")
    return FileResponse(candidate, media_type="application/pdf")


@app.get("/api/debug/heatmap")
async def heatmap(query: str, chunk_index: int = 0, _user: str = Depends(verify_token)) -> JSONResponse:
    """Sentence-level cosine similarity between query and a stored chunk."""
    import numpy as np

    agent = await _get_agent()
    graphrag = agent.graphrag
    loop = asyncio.get_event_loop()

    # Retrieve the chunk from Qdrant by chunk_index payload filter
    def _fetch_chunk() -> str | None:
        try:
            from qdrant_client.http.models import Filter, FieldCondition, MatchValue
            hits = graphrag._qdrant_client().scroll(
                collection_name=graphrag.config["collection"],
                scroll_filter=Filter(
                    must=[
                        FieldCondition(
                            key="chunk_index",
                            match=MatchValue(value=chunk_index),
                        ),
                        FieldCondition(
                            key="scope",
                            match=MatchValue(
                                value=graphrag.config.get("scope", "literature")
                            ),
                        ),
                    ]
                ),
                limit=1,
                with_payload=True,
            )[0]
            return hits[0].payload.get("content", "") if hits else None
        except Exception as exc:
            logger.warning("heatmap fetch failed: %s", exc)
            return None

    content = await loop.run_in_executor(None, _fetch_chunk)
    if not content:
        return JSONResponse({"query": query, "sentences": []})

    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", content) if len(s.strip()) > 10]

    def _score() -> list[dict]:
        embedder = graphrag._embedder_model()
        q_vec = embedder.encode(query)
        s_vecs = embedder.encode(sentences)
        scores = (s_vecs @ q_vec) / (
            np.linalg.norm(s_vecs, axis=1) * np.linalg.norm(q_vec) + 1e-9
        )
        return [{"text": s, "score": round(float(sc), 4)} for s, sc in zip(sentences, scores)]

    scored = await loop.run_in_executor(None, _score)
    return JSONResponse({"query": query, "sentences": scored})


@app.get("/api/debug/subgraph/{entity:path}")
async def subgraph(
    entity: str,
    target: Literal["literature", "patient_context"] = "literature",
    source_slug: str | None = None,
    _user: str = Depends(verify_token),
) -> JSONResponse:
    """Return 1-hop Neo4j neighbourhood for an entity (D3 force-graph format)."""
    if target == "patient_context" and not source_slug:
        raise HTTPException(status_code=422, detail="source_slug is required")
    agent = await _get_agent()
    graphrag = agent.graphrag
    loop = asyncio.get_event_loop()
    target_config = graphrag._target_config(target)
    graph_source = f"{source_slug}_chunks" if source_slug else None

    cypher = """
        MATCH (h)-[r]->(t)
        WHERE r.scope = $scope
          AND ($source IS NULL OR r.source = $source)
          AND (toLower(h.name) CONTAINS toLower($entity)
           OR toLower(t.name) CONTAINS toLower($entity)
          )
        RETURN h.name AS head, type(r) AS relation, t.name AS tail,
               labels(h)[0] AS head_label, labels(t)[0] AS tail_label
        LIMIT 60
    """

    def _query() -> dict:
        from neo4j.exceptions import Neo4jError

        try:
            with graphrag._neo4j_driver().session() as session:
                records = list(
                    session.run(
                        cypher,
                        entity=entity,
                        scope=target_config["scope"],
                        source=graph_source,
                    )
                )
        except (Neo4jError, ConnectionError, OSError, TimeoutError) as exc:
            logger.warning("subgraph query failed: %s", type(exc).__name__)
            return {"entity": entity, "nodes": [], "links": []}

        node_map: dict[str, dict] = {}
        links = []
        for r in records:
            h, rel, t = r["head"], r["relation"], r["tail"]
            for name, label in ((h, r.get("head_label")), (t, r.get("tail_label"))):
                if name not in node_map:
                    node_map[name] = {
                        "id": name,
                        "label": label or "Entity",
                        "tier": 1 if name.upper() == entity.upper() else 2,
                    }
            links.append({"source": h, "target": t, "relation": rel})

        return {"entity": entity, "nodes": list(node_map.values()), "links": links}

    result = await loop.run_in_executor(None, _query)
    return JSONResponse(result)


class SynthesisRequest(BaseModel):
    query: str
    evidence: list[Any] = Field(default_factory=list)
    evidenceId: str | None = None


class SynthesisStreamRequest(BaseModel):
    query: str
    evidenceId: str


def _require_cached_evidence(query: str, evidence_id: str) -> dict[str, Any]:
    record = _cache_get(evidence_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "evidence_expired",
                "message": "Retrieved evidence is no longer available. Run the query again.",
                "retryable": True,
            },
        )
    if record["query"] != query:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "evidence_mismatch",
                "message": "The evidence does not belong to this query.",
                "retryable": False,
            },
        )
    evidence = record["evidence"]
    if not evidence.get("found", False):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "empty_evidence",
                "message": "Synthesis requires retrieved evidence.",
                "retryable": False,
            },
        )
    return evidence


def _sse_event(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"


@app.post("/api/synthesis")
async def synthesis(req: SynthesisRequest, _user: str = Depends(verify_token)) -> JSONResponse:
    """Phase 2 — LLM synthesis. Uses cached GraphRAG evidence if available."""
    agent = await _get_agent()
    loop = asyncio.get_event_loop()

    if req.evidenceId:
        ev = _require_cached_evidence(req.query, req.evidenceId)
    else:
        # Compatibility path for non-UI clients: default to literature retrieval.
        ev = await loop.run_in_executor(None, agent.graphrag.cached_execute, req.query)
        if not isinstance(ev, dict):
            ev = {"found": False}

    from .agent import LLMUnavailableError, SynthesisInputTooLargeError

    try:
        result = await loop.run_in_executor(None, agent.synthesize, req.query, ev)
    except SynthesisInputTooLargeError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "synthesis_input_too_large",
                "message": exc.detail,
                "retryable": False,
            },
        ) from exc
    except LLMUnavailableError as exc:
        logger.warning("Synthesis unavailable: error=%s", exc.detail)
        raise HTTPException(
            status_code=503,
            detail={
                "code": "synthesis_unavailable",
                "message": exc.detail,
                "retryable": True,
            },
        ) from exc

    return JSONResponse(
        {
            "synthesis": result.text,
            "model": result.model,
            "fallbackUsed": result.fallback_used,
            "tokensUsed": None,
        }
    )


@app.post("/api/synthesis/stream")
async def synthesis_stream(req: SynthesisStreamRequest, _user: str = Depends(verify_token)) -> StreamingResponse:
    """Stream grounded synthesis tokens for one exact cached evidence result."""
    agent = await _get_agent()
    evidence = _require_cached_evidence(req.query, req.evidenceId)
    loop = asyncio.get_event_loop()

    from .agent import LLMUnavailableError, SynthesisInputTooLargeError

    try:
        prepared = await loop.run_in_executor(
            None,
            agent.prepare_synthesis_stream,
            req.query,
            evidence,
        )
    except SynthesisInputTooLargeError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "synthesis_input_too_large",
                "message": exc.detail,
                "retryable": False,
            },
        ) from exc
    except LLMUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "synthesis_unavailable",
                "message": exc.detail,
                "retryable": True,
            },
        ) from exc

    def generate():
        yield _sse_event(
            {
                "type": "meta",
                "model": prepared.model,
                "fallbackUsed": prepared.fallback_used,
            }
        )
        try:
            for event in prepared.events:
                if event.type == "meta":
                    yield _sse_event(
                        {
                            "type": "meta",
                            "model": event.model,
                            "fallbackUsed": event.fallback_used,
                        }
                    )
                else:
                    yield _sse_event({"type": "token", "text": event.text})
        except LLMUnavailableError as exc:
            logger.warning(
                "Synthesis stream terminated: evidence_id=%s error=%s",
                req.evidenceId,
                type(exc).__name__,
            )
            yield _sse_event(
                {
                    "type": "error",
                    "code": "synthesis_unavailable",
                    "message": exc.detail,
                    "retryable": True,
                }
            )
            return
        yield _sse_event({"type": "done"})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
