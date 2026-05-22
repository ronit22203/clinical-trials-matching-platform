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
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]

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


async def _get_agent() -> Any:
    global _agent
    if _agent is None:
        async with _agent_init_lock:
            if _agent is None:
                from .agent import Agent

                loop = asyncio.get_event_loop()
                logger.info("Initialising Agent (first request)…")
                _agent = await loop.run_in_executor(None, Agent.from_config)
                logger.info("Agent ready.")
    return _agent


# ── Evidence cache: store last 32 GraphRAG results keyed by normalised query ──

_evidence_cache: OrderedDict[str, dict] = OrderedDict()
_CACHE_MAX = 32


def _cache_put(query: str, evidence: dict) -> None:
    key = query.strip().lower()
    _evidence_cache[key] = evidence
    if len(_evidence_cache) > _CACHE_MAX:
        _evidence_cache.popitem(last=False)


def _cache_get(query: str) -> Optional[dict]:
    return _evidence_cache.get(query.strip().lower())


# ── Helpers ───────────────────────────────────────────────────────────────────

_GRAPH_FACT_RE = re.compile(r"^(.+?)\s+--\[(.+?)\]-->\s+(.+)$")


def _parse_graph_fact(fact: str) -> Optional[dict]:
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
                "score": hit.get("reranker_score") or hit.get("score", 0),
                "source": source,
                "content": hit.get("content", ""),
                "context": hit.get("context") or "",
                "evidence": evidence_entries,
            }
        )
    return matches


# ── Routes ────────────────────────────────────────────────────────────────────


@app.post("/api/match")
async def match(
    query: str = Form(...),
    file: Optional[UploadFile] = File(default=None),
) -> JSONResponse:
    """Phase 1 — GraphRAG hybrid retrieval. Returns matches for the UI."""
    agent = await _get_agent()
    t0 = time.perf_counter()

    loop = asyncio.get_event_loop()
    evidence = await loop.run_in_executor(None, agent.graphrag.cached_execute, query)
    if not isinstance(evidence, dict):
        evidence = {"found": False, "error": str(evidence)}

    _cache_put(query, evidence)

    latency_ms = round((time.perf_counter() - t0) * 1000, 1)
    matches = _graphrag_to_matches(evidence) if evidence.get("found") else []

    return JSONResponse(
        {
            "query": query,
            "found": evidence.get("found", False),
            "matches": matches,
            "graphFacts": evidence.get("graph_facts", []),
            "latency_ms": latency_ms,
        }
    )


@app.get("/api/verify")
async def verify(source: str, byte_start: int = 0, byte_end: int = 512) -> JSONResponse:
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
async def stats() -> JSONResponse:
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


@app.get("/api/pdf/{doi_path:path}")
async def serve_pdf(doi_path: str) -> FileResponse:
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
async def heatmap(query: str, chunk_index: int = 0) -> JSONResponse:
    """Sentence-level cosine similarity between query and a stored chunk."""
    import numpy as np

    agent = await _get_agent()
    graphrag = agent.graphrag
    loop = asyncio.get_event_loop()

    # Retrieve the chunk from Qdrant by chunk_index payload filter
    def _fetch_chunk() -> Optional[str]:
        try:
            from qdrant_client.http.models import Filter, FieldCondition, MatchValue
            hits = graphrag._qdrant_client().scroll(
                collection_name=graphrag.config["collection"],
                scroll_filter=Filter(
                    must=[FieldCondition(key="chunk_index", match=MatchValue(value=chunk_index))]
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
async def subgraph(entity: str) -> JSONResponse:
    """Return 1-hop Neo4j neighbourhood for an entity (D3 force-graph format)."""
    agent = await _get_agent()
    graphrag = agent.graphrag
    loop = asyncio.get_event_loop()

    cypher = """
        MATCH (h)-[r]->(t)
        WHERE toLower(h.name) CONTAINS toLower($entity)
           OR toLower(t.name) CONTAINS toLower($entity)
        RETURN h.name AS head, type(r) AS relation, t.name AS tail,
               labels(h)[0] AS head_label, labels(t)[0] AS tail_label
        LIMIT 60
    """

    def _query() -> dict:
        try:
            with graphrag._neo4j_driver().session() as session:
                records = list(session.run(cypher, entity=entity))
        except Exception as exc:
            logger.warning("subgraph query failed: %s", exc)
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
    evidence: list[Any]


@app.post("/api/synthesis")
async def synthesis(req: SynthesisRequest) -> JSONResponse:
    """Phase 2 — LLM synthesis. Uses cached GraphRAG evidence if available."""
    agent = await _get_agent()
    loop = asyncio.get_event_loop()

    # Prefer cached evidence from a recent /api/match call for this query
    cached = _cache_get(req.query)
    if cached and cached.get("found"):
        ev = cached
    else:
        # Fall back: run GraphRAG retrieval on demand
        ev = await loop.run_in_executor(None, agent.graphrag.cached_execute, req.query)
        if not isinstance(ev, dict):
            ev = {"found": False}
        _cache_put(req.query, ev)

    def _synthesize() -> str:
        from .agent import _format_evidence, _NO_EVIDENCE_RESPONSE
        from langchain_core.messages import HumanMessage, SystemMessage

        if not ev.get("found"):
            return _NO_EVIDENCE_RESPONSE

        context = _format_evidence(ev)
        messages = [
            SystemMessage(content=agent.config.system_prompt),
            HumanMessage(
                content=f"[QUERY]\n{req.query}\n\n[EVIDENCE]\n{context}\n[/EVIDENCE]"
            ),
        ]
        resp = agent.llm.invoke(messages)
        return resp.content or _NO_EVIDENCE_RESPONSE

    text = await loop.run_in_executor(None, _synthesize)
    model_name = agent.config.model

    return JSONResponse({"synthesis": text, "model": model_name, "tokensUsed": None})
