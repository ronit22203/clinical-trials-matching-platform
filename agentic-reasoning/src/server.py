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

import csv
import glob as _glob
import io
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from .config_loader import load_agent_config, load_app_config
from .agent import SimpleAgent

# Lazy-loaded to avoid startup cost when tools aren't configured
try:
    from .tools.registry import ToolRegistry
    _registry_available = True
except ImportError:
    _registry_available = False

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]

# ── Output sanitization ────────────────────────────────────────────────────────

def _sanitize_output(text: str) -> str:
    """Strip Qwen3 chain-of-thought tags from agent synthesis before returning."""
    text = re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL)
    text = text.replace("<think>", "").replace("</think>", "")
    return text.strip()


# ── GraphRAG singleton ────────────────────────────────────────────────────────

_graphrag_tool_instance = None


def _get_graphrag_tool():
    """Lazy singleton for GraphRAGTool — loads embedding/reranker models once."""
    global _graphrag_tool_instance
    if _graphrag_tool_instance is None:
        from .tools.implementations.graphrag_tools import GraphRAGTool
        app_cfg = load_app_config()
        tool_cfg = app_cfg["agentic_reasoning"]["tools"]["graphrag"]["config"]
        _graphrag_tool_instance = GraphRAGTool(tool_cfg)
        logger.info("GraphRAGTool singleton initialised")
    return _graphrag_tool_instance


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
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "http://localhost:8080",
        "null",  # file:// origin for local dev
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


class EvidenceFact(CamelModel):
    head: str
    relation: str
    tail: str
    tier: int = 2
    byte_start: int | None = None
    byte_end: int | None = None
    chunk_id: int | None = None


class MatchResult(CamelModel):
    score: float
    reranker_score: float | None = None
    content: str
    source: str
    context: str | None = None
    chunk_id: int | None = None
    chunk_index: int | None = None
    evidence: list[EvidenceFact] = Field(default_factory=list)


class MatchResponse(CamelModel):
    execution_id: str
    query: str
    keywords: list[str]
    matches: list[MatchResult]
    graph_facts: list[str]
    latency_ms: int


class SynthesisEvidenceFact(BaseModel):
    head: str
    relation: str
    tail: str
    tier: int = 2


class SynthesisRequest(BaseModel):
    query: str
    evidence: list[SynthesisEvidenceFact]


class SynthesisResponse(CamelModel):
    synthesis: str
    model: str
    tokens_used: int


class VerifyResponse(BaseModel):
    source: str
    byte_start: int
    byte_end: int
    snippet: str
    pdf_url: Optional[str] = None
    highlight_url: Optional[str] = None


class StatsResponse(BaseModel):
    run_id: str
    recall_at_5: float
    ndcg_at_5: float
    mrr: float
    hit_rate_at_5: float
    entity_f1_relaxed: float
    ttft_p50_ms: float
    throughput_tok_s: float
    failure_rate: float


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


@app.post("/api/match", response_model=MatchResponse)
async def match_trials(
    query: str = Form(...),
    file: UploadFile | None = File(default=None),
) -> MatchResponse:
    start = time.monotonic()
    execution_id = str(uuid.uuid4())[:8]

    # Build effective query — optionally augmented from first CSV row
    effective_query = query.strip()
    if file is not None:
        try:
            raw_bytes = await file.read()
            reader = csv.DictReader(io.StringIO(raw_bytes.decode("utf-8")))
            rows = list(reader)
            if rows:
                parts = [effective_query] if effective_query else []
                for key, val in rows[0].items():
                    if val and key.lower() not in ("patient_id", "id"):
                        parts.append(f"{key}: {val}")
                effective_query = ". ".join(parts)
        except Exception as exc:
            logger.warning("CSV parse failed: %s", exc)

    if not effective_query:
        raise HTTPException(status_code=422, detail="query or non-empty CSV required")

    # Call the GraphRAG tool
    try:
        tool = _get_graphrag_tool()
    except Exception as exc:
        logger.error("GraphRAGTool init failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=503, detail=f"Tool unavailable: {exc}") from exc

    try:
        raw = tool.execute(effective_query)
    except Exception as exc:
        logger.error("GraphRAG execute failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Retrieval error: {exc}") from exc

    if isinstance(raw, str):
        raise HTTPException(status_code=500, detail=raw)

    vector_results: list[dict] = raw.get("vector_results", [])
    graph_facts: list[str] = raw.get("graph_facts", [])
    keywords: list[str] = raw.get("keywords", [])

    # Fetch structured evidence (tier + byte-range) from Neo4j
    doi_prefixes: list[str] = []
    for vr in vector_results:
        src = vr.get("source", "")
        doi = re.sub(r"_cleaned\.md$", "", src) if src else ""
        if doi and doi not in doi_prefixes:
            doi_prefixes.append(doi)

    evidence_by_chunk_index: dict[int, list[EvidenceFact]] = {}
    all_evidence: list[EvidenceFact] = []

    if doi_prefixes:
        try:
            driver = tool._neo4j_driver()
            cypher = """
                MATCH (h)-[r]->(t)
                WHERE any(doi IN $dois WHERE r.source CONTAINS doi)
                RETURN h.name AS head, type(r) AS relation, t.name AS tail,
                       r.tier AS tier, r.byte_start AS byte_start,
                       r.byte_end AS byte_end, r.chunk_id AS chunk_id
                LIMIT 60
            """
            with driver.session() as session:
                records = list(session.run(cypher, dois=doi_prefixes))

            for rec in records:
                fact = EvidenceFact(
                    head=rec["head"],
                    relation=rec["relation"],
                    tail=rec["tail"],
                    tier=rec["tier"] or 2,
                    byte_start=rec["byte_start"],
                    byte_end=rec["byte_end"],
                    chunk_id=rec["chunk_id"],
                )
                all_evidence.append(fact)
                cid = rec["chunk_id"]
                if cid is not None:
                    evidence_by_chunk_index.setdefault(int(cid), []).append(fact)
        except Exception as exc:
            logger.warning("Structured evidence query failed: %s", exc)

    # Assemble MatchResult list — deduplicate by chunk_index then content prefix
    matches: list[MatchResult] = []
    seen_keys: set[str] = set()
    for i, vr in enumerate(vector_results):
        chunk_index = vr.get("chunk_index")
        dedup_key = str(chunk_index) if chunk_index is not None else vr.get("content", "")[:120]
        if dedup_key in seen_keys:
            continue
        seen_keys.add(dedup_key)

        if chunk_index is not None and chunk_index in evidence_by_chunk_index:
            evidence = evidence_by_chunk_index[chunk_index][:10]
        elif not matches and all_evidence:
            evidence = all_evidence[:10]
        else:
            evidence = []

        matches.append(MatchResult(
            score=vr.get("score", 0.0),
            reranker_score=vr.get("reranker_score"),
            content=vr.get("content", ""),
            source=vr.get("source", ""),
            context=vr.get("context"),
            chunk_id=vr.get("chunk_id"),
            chunk_index=chunk_index,
            evidence=evidence,
        ))

    latency_ms = int((time.monotonic() - start) * 1000)
    return MatchResponse(
        execution_id=execution_id,
        query=effective_query,
        keywords=keywords,
        matches=matches,
        graph_facts=graph_facts,
        latency_ms=latency_ms,
    )


# ── Tier labels used in synthesis prompt ─────────────────────────────────────
_TIER_LABEL = {1: "verbatim", 2: "stated", 3: "inferred"}

_SYNTHESIS_SYSTEM = (
    "You are a clinical research assistant. Synthesise a concise, evidence-grounded answer "
    "to the clinical query below. Base your answer ONLY on the structured evidence provided. "
    "Do not hallucinate. Be precise. Write 3-5 sentences maximum."
)


@app.post("/api/synthesis", response_model=SynthesisResponse)
async def synthesize(request: SynthesisRequest) -> SynthesisResponse:
    """Generate a concise LLM synthesis from structured evidence facts."""
    if not request.evidence:
        raise HTTPException(status_code=400, detail="No evidence provided")

    facts_text = "\n".join(
        f"- {f.head} {f.relation} {f.tail} [{_TIER_LABEL.get(f.tier, 'stated')}]"
        for f in request.evidence
    )
    user_msg = f"EVIDENCE:\n{facts_text}\n\nQUERY: {request.query}"

    try:
        app_cfg = load_app_config()
        model_str: str = app_cfg["agentic_reasoning"]["agent"]["model"]
    except Exception:
        model_str = "lmstudio/qwen3-8b"

    try:
        from .llm_factory import build_llm
        from langchain_core.messages import HumanMessage, SystemMessage

        llm = build_llm(model_str, temperature=0.1, max_tokens=512)
        response = await llm.ainvoke([
            SystemMessage(content=_SYNTHESIS_SYSTEM),
            HumanMessage(content=user_msg),
        ])
        synthesis_text = _sanitize_output(str(response.content))
        tokens_used = (
            response.usage_metadata.get("output_tokens", 0)
            if hasattr(response, "usage_metadata") and response.usage_metadata
            else 0
        )
    except Exception as exc:
        logger.warning("Synthesis LLM call failed: %s", exc)
        raise HTTPException(status_code=503, detail=f"LLM unavailable: {exc}") from exc

    # model_str is "provider/model-name" — return just the model name for display
    display_model = model_str.split("/", 1)[-1] if "/" in model_str else model_str
    return SynthesisResponse(
        synthesis=synthesis_text,
        model=display_model,
        tokens_used=tokens_used,
    )


@app.get("/api/pdf/{doi_path:path}")
async def get_pdf(doi_path: str) -> FileResponse:
    pattern = str(_REPO_ROOT / "data" / "pdfs" / "raw" / "**" / doi_path / "paper.pdf")
    found = _glob.glob(pattern, recursive=True)
    if not found:
        raise HTTPException(status_code=404, detail=f"PDF not found for: {doi_path}")
    return FileResponse(found[0], media_type="application/pdf")




@app.get("/api/debug/heatmap")
async def debug_heatmap(query: str, chunk_index: int) -> dict:
    """Sentence-level cosine similarity between query and each sentence in the chunk."""
    import numpy as np
    import re as _re

    tool = _get_graphrag_tool()

    # Fetch chunk text from Qdrant
    from qdrant_client.models import Filter, FieldCondition, MatchValue
    try:
        pts, _ = tool._qdrant_client().scroll(
            tool.config["collection"],
            scroll_filter=Filter(must=[
                FieldCondition(key="chunk_index", match=MatchValue(value=chunk_index))
            ]),
            limit=1,
            with_payload=True,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Qdrant error: {exc}") from exc

    if not pts:
        raise HTTPException(status_code=404, detail=f"No chunk with index {chunk_index}")

    chunk_text: str = pts[0].payload.get("content", "")
    context: str = pts[0].payload.get("context", "")

    # Split into sentences (keep non-empty, min 10 chars)
    sentences = [s.strip() for s in _re.split(r"(?<=[.!?])\s+", chunk_text) if len(s.strip()) >= 10]
    if not sentences:
        sentences = [chunk_text]

    # Embed query + sentences
    embedder = tool._embedder_model()
    all_texts = [query] + sentences
    vecs = embedder.encode(all_texts, show_progress_bar=False)

    query_vec = vecs[0]
    sent_vecs = vecs[1:]

    # Cosine similarity
    norms = np.linalg.norm(sent_vecs, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1e-9, norms)
    sent_vecs_normed = sent_vecs / norms
    q_norm = np.linalg.norm(query_vec)
    scores = (sent_vecs_normed @ query_vec / (q_norm + 1e-9)).tolist()

    return {
        "query": query,
        "context": context,
        "chunk_index": chunk_index,
        "sentences": [
            {"text": s, "score": round(float(sc), 4)}
            for s, sc in zip(sentences, scores)
        ],
    }


@app.get("/api/debug/subgraph/{entity}")
async def debug_subgraph(entity: str) -> dict:
    """Return 1-hop Neo4j neighbourhood for a given entity (for D3 force graph)."""
    tool = _get_graphrag_tool()
    cypher = """
        MATCH (n)-[r]-(m)
        WHERE n.name = $name OR toLower(n.name) CONTAINS toLower($name)
        RETURN n.name AS src, type(r) AS rel, m.name AS tgt,
               r.tier AS tier, r.byte_start AS byte_start, r.byte_end AS byte_end
        LIMIT 30
    """
    try:
        with tool._neo4j_driver().session() as session:
            records = list(session.run(cypher, name=entity.upper()))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Neo4j error: {exc}") from exc

    nodes_map: dict[str, dict] = {}
    links = []
    for rec in records:
        for n in (rec["src"], rec["tgt"]):
            if n and n not in nodes_map:
                nodes_map[n] = {"id": n, "label": n, "isRoot": n.upper() == entity.upper()}
        if rec["src"] and rec["tgt"]:
            links.append({
                "source": rec["src"],
                "target": rec["tgt"],
                "label": rec["rel"],
                "tier": rec["tier"] or 2,
                "byteStart": rec["byte_start"],
                "byteEnd": rec["byte_end"],
            })

    return {
        "entity": entity.upper(),
        "nodes": list(nodes_map.values()),
        "links": links,
    }


@app.get("/api/verify/highlight")
async def verify_highlight(source: str, byte_start: int, byte_end: int):
    """Return full-PDF JPEG with matched paragraph highlighted (disk-cached)."""
    import fitz
    from fastapi import Response as _R
    from PIL import Image as _PILImage
    import io as _io, hashlib as _hl

    # ── disk cache ────────────────────────────────────────────────────────────
    cache_dir = _REPO_ROOT / "data" / "artifacts" / "highlight_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_key  = _hl.md5(f"{source}:{byte_start}:{byte_end}".encode()).hexdigest()
    cache_file = cache_dir / f"{cache_key}.jpg"
    if cache_file.exists():
        return _R(content=cache_file.read_bytes(), media_type="image/jpeg",
                  headers={"Cache-Control": "no-store"})

    filename = Path(source).name
    clean_dir = _REPO_ROOT / "data" / "artifacts" / "clean"
    file_path = clean_dir / filename
    if not file_path.exists():
        candidates = list(clean_dir.glob("*_cleaned.md"))
        file_path = candidates[0] if candidates else None
    if not file_path:
        raise HTTPException(status_code=404, detail="Source file not found")

    raw_snippet = file_path.read_text(encoding="utf-8")[byte_start:byte_end].strip()

    # Build overlapping 60-char search chunks — covers multi-sentence spans
    clean = raw_snippet.replace("\n", " ")
    step = 30
    chunk_len = 65
    search_chunks = []
    for i in range(0, len(clean), step):
        chunk = clean[i : i + chunk_len].strip()
        if len(chunk) >= 20:
            search_chunks.append(chunk)
    if not search_chunks:
        search_chunks = [clean[:80]]

    stem = re.sub(r"_cleaned\.md$", "", file_path.name)
    pdf_hits = _glob.glob(
        str(_REPO_ROOT / "data" / "pdfs" / "raw" / "**" / stem / "paper.pdf"),
        recursive=True,
    )
    if not pdf_hits:
        raise HTTPException(status_code=404, detail="PDF not found")

    try:
        doc = fitz.open(str(pdf_hits[0]))
        n_pages = len(doc)

        # Find the page with the most hits across all chunks
        page_hits: dict[int, list] = {}
        for chunk in search_chunks:
            for i, page in enumerate(doc):
                rects = page.search_for(chunk)
                if rects:
                    page_hits.setdefault(i, []).extend(rects)

        # Pick page with most match rectangles; default to 0
        target_page = max(page_hits, key=lambda k: len(page_hits[k])) if page_hits else 0

        # Render ALL pages — highlight only the target page
        mat = fitz.Matrix(1.8, 1.8)

        pixmaps = []
        for pi in range(n_pages):
            pg = doc[pi]
            if pi == target_page and pi in page_hits:
                seen: set = set()
                for rect in page_hits[pi]:
                    key = (round(rect.x0), round(rect.y0))
                    if key not in seen:
                        seen.add(key)
                        annot = pg.add_highlight_annot(rect)
                        annot.set_colors(stroke=[1.0, 0.85, 0.0])
                        annot.update()
            pixmaps.append(pg.get_pixmap(matrix=mat, alpha=False))

        # Stack all pages → JPEG (5-8× smaller than PNG, ~300ms faster transfer)
        from PIL import Image as _PILImage
        import io as _io, hashlib as _hl

        pil_pages = [_PILImage.frombytes("RGB", (p.width, p.height), p.samples) for p in pixmaps]
        total_h = sum(p.height for p in pil_pages)
        combined_img = _PILImage.new("RGB", (pil_pages[0].width, total_h), (255, 255, 255))
        y = 0
        for p in pil_pages:
            combined_img.paste(p, (0, y))
            y += p.height

        buf = _io.BytesIO()
        combined_img.save(buf, format="JPEG", quality=82, optimize=True)
        jpg = buf.getvalue()
        doc.close()

        # write to disk cache
        cache_key  = _hl.md5(f"{source}:{byte_start}:{byte_end}".encode()).hexdigest()
        cache_dir  = _REPO_ROOT / "data" / "artifacts" / "highlight_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / f"{cache_key}.jpg").write_bytes(jpg)

    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return _R(content=jpg, media_type="image/jpeg",
              headers={"Cache-Control": "no-store"})


@app.get("/api/verify", response_model=VerifyResponse)
async def verify_chunk(source: str, byte_start: int, byte_end: int) -> VerifyResponse:
    filename = Path(source).name  # strip any path traversal
    clean_dir = _REPO_ROOT / "data" / "artifacts" / "clean"
    file_path = clean_dir / filename
    if not file_path.exists():
        # Fall back: the source may be a legacy hash name; find any .md in clean dir
        candidates = list(clean_dir.glob("*_cleaned.md"))
        if not candidates:
            raise HTTPException(status_code=404, detail=f"Source file not found: {filename}")
        file_path = candidates[0]
        logger.warning("verify_chunk: %s not found, falling back to %s", filename, file_path.name)
    text = file_path.read_text(encoding="utf-8")
    snippet = text[byte_start:byte_end]

    # Resolve PDF and build highlight url
    pdf_url: Optional[str] = None
    highlight_url: Optional[str] = None
    stem = re.sub(r"_cleaned\.md$", "", file_path.name)
    pdf_hits = _glob.glob(
        str(_REPO_ROOT / "data" / "pdfs" / "raw" / "**" / stem / "paper.pdf"),
        recursive=True,
    )
    if pdf_hits:
        pp = Path(pdf_hits[0])
        doi_path = f"{pp.parent.parent.name}/{pp.parent.name}"
        pdf_url = f"/api/pdf/{doi_path}"
        qs = f"source={source}&byte_start={byte_start}&byte_end={byte_end}"
        highlight_url = f"/api/verify/highlight?{qs}"

    return VerifyResponse(
        source=file_path.name,
        byte_start=byte_start,
        byte_end=byte_end,
        snippet=snippet,
        pdf_url=pdf_url,
        highlight_url=highlight_url,
    )


@app.get("/api/stats", response_model=StatsResponse)
async def get_stats() -> StatsResponse:
    pattern = str(_REPO_ROOT / "benchmarking" / "results" / "det_*" / "manifest.json")
    manifests = sorted(_glob.glob(pattern), reverse=True)
    if not manifests:
        raise HTTPException(status_code=404, detail="No benchmark results found")
    with open(manifests[0]) as f:
        data = json.load(f)
    run_id = Path(manifests[0]).parent.name
    s: dict[str, Any] = data.get("summary", {})
    return StatsResponse(
        run_id=run_id,
        recall_at_5=s.get("recall_at_5", 0.0),
        ndcg_at_5=s.get("ndcg_at_5", 0.0),
        mrr=s.get("mrr", 0.0),
        hit_rate_at_5=s.get("hit_rate_at_5", 0.0),
        entity_f1_relaxed=s.get("entity_f1_relaxed", 0.0),
        ttft_p50_ms=s.get("ttft_p50_ms", 0.0),
        throughput_tok_s=s.get("throughput_tok_s", 0.0),
        failure_rate=s.get("failure_rate", 0.0),
    )


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
