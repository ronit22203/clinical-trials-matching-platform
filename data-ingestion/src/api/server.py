"""
Ingestion Pipeline API — serves on :8001
Provides SSE-streamed pipeline execution and artifact serving for simple-ui.

Required packages (not in base requirements.txt):
  pip install fastapi uvicorn[standard] python-multipart
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

# ── Path setup ────────────────────────────────────────────────────────────────
# server.py is at data-ingestion/src/api/server.py
_API_DIR      = Path(__file__).parent
_SRC_DIR      = _API_DIR.parent
_PROJECT_ROOT = _SRC_DIR.parent          # data-ingestion/
_REPO_ROOT    = _PROJECT_ROOT.parent     # repo root

if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.config_loader import load_ingestion_config  # noqa: E402

# ── Directories (resolved at import time from config) ─────────────────────────
_CONFIG_PATH  = _REPO_ROOT / "config" / "app.yaml"
_CONFIG       = load_ingestion_config(_CONFIG_PATH)
_OUTPUT       = _CONFIG.get("output", {})

UPLOAD_DIR    = _REPO_ROOT / "data" / "pdfs" / "raw" / "upload"
OCR_DIR       = _REPO_ROOT / _OUTPUT.get("ocr_dir",      "data/artifacts/extract").lstrip("./")
MARKDOWN_DIR  = _REPO_ROOT / _OUTPUT.get("markdown_dir", "data/artifacts/convert").lstrip("./")
CLEANED_DIR   = _REPO_ROOT / _OUTPUT.get("cleaned_dir",  "data/artifacts/clean").lstrip("./")
CHUNKS_DIR    = _REPO_ROOT / _OUTPUT.get("chunks_dir",   "data/artifacts/chunk").lstrip("./")

for _d in (UPLOAD_DIR, OCR_DIR, MARKDOWN_DIR, CLEANED_DIR, CHUNKS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ── FastAPI app ────────────────────────────────────────────────────────────────
app = FastAPI(title="Ingestion Pipeline API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # local-only; tighten in production
    allow_methods=["*"],
    allow_headers=["*"],
)

log = logging.getLogger("ingestion_api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")


# ── SSE helpers ───────────────────────────────────────────────────────────────

def _sse_line(event: dict) -> bytes:
    """Encode a dict as a single SSE data line."""
    return f"data: {json.dumps(event)}\n\n".encode()


# ── Pipeline runner (runs in thread executor) ─────────────────────────────────

def _run_pipeline(pdf_path: Path, slug: str, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop) -> None:
    """Execute 5-stage ingestion pipeline, pushing SSE events into *queue*."""

    def emit(stage: str, status: str, message: str, extra: dict | None = None) -> None:
        event: dict = {"stage": stage, "status": status, "message": message}
        if extra:
            event["extra"] = extra
        asyncio.run_coroutine_threadsafe(queue.put(event), loop)

    try:
        from src.extractors.pdf_marker_v2 import (
            initialize_models,
            load_pdf_images,
            serialize_surya_results,
        )
        from src.extractors.surya_converter import SuryaToMarkdown
        from src.processors.chunker import MarkdownChunker
        from src.processors.cleaner import TextCleaner
        from src.storage.embedder import MedicalVectorizer
        from PIL import ImageDraw

        cfg     = load_ingestion_config(_CONFIG_PATH)
        ocr_cfg = cfg.get("ocr", {})

        emit("init", "running", f"Pipeline initialised for '{slug}'")

        # ── Stage 1: PDF → OCR JSON ───────────────────────────────────────────
        emit("ocr", "running", "Loading Surya OCR models…")
        device = ocr_cfg.get("device", "mps")
        predictors = initialize_models(device=device)

        emit("ocr", "running", "Rendering PDF pages…")
        images = load_pdf_images(str(pdf_path))
        emit("ocr", "running", f"Running OCR on {len(images)} page(s)…")

        det_pred = predictors["detection"]
        rec_pred = predictors["recognition"]
        results  = []

        for i, image in enumerate(images):
            detection_result = det_pred([image])
            bboxes = []
            for poly_box in detection_result[0].bboxes:
                if hasattr(poly_box, "polygon") and poly_box.polygon:
                    xs = [p[0] for p in poly_box.polygon]
                    ys = [p[1] for p in poly_box.polygon]
                    bboxes.append([min(xs), min(ys), max(xs), max(ys)])
            if bboxes:
                rec = rec_pred(images=[image], bboxes=[bboxes])
                results.append(rec[0])

        # Serialize OCR JSON
        json_output   = serialize_surya_results(results)
        ocr_json_path = OCR_DIR / f"{slug}_ocr.json"
        ocr_json_path.parent.mkdir(parents=True, exist_ok=True)
        with open(ocr_json_path, "w", encoding="utf-8") as fh:
            json.dump(json_output, fh, indent=2, ensure_ascii=False)

        # Save debug visualizations
        viz_dir   = OCR_DIR / slug / "debug_visualizations"
        viz_dir.mkdir(parents=True, exist_ok=True)
        conf_thr  = ocr_cfg.get("confidence_threshold", 0.80)
        page_info = []

        for i, (image, result) in enumerate(zip(images, results)):
            img_copy = image.copy()
            draw     = ImageDraw.Draw(img_copy)
            for line in result.text_lines:
                color = "green" if line.confidence >= conf_thr else "red"
                draw.rectangle(line.bbox, outline=color, width=2)
            img_name = f"{slug}_page_{i + 1:03d}_debug.png"
            img_copy.save(viz_dir / img_name)
            page_info.append({"page": i + 1, "lines": len(result.text_lines)})

        emit("ocr", "done", f"OCR complete — {len(images)} page(s), viz saved",
             {"pages": len(images), "slug": slug, "page_info": page_info})

        # ── Stage 2: OCR JSON → Markdown ─────────────────────────────────────
        emit("convert", "running", "Converting OCR → Markdown…")
        converter = SuryaToMarkdown(config=cfg)
        markdown  = converter.convert(json_output)

        md_path   = MARKDOWN_DIR / f"{slug}_converted.md"
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(markdown, encoding="utf-8")
        emit("convert", "done", f"Conversion complete — {len(markdown):,} chars",
             {"chars": len(markdown), "slug": slug})

        # ── Stage 3: Clean Markdown ───────────────────────────────────────────
        emit("clean", "running", "Cleaning text (PII redaction, noise removal)…")
        cleaner   = TextCleaner(config=cfg)
        cleaned   = cleaner.clean(markdown)

        clean_path = CLEANED_DIR / f"{slug}_cleaned.md"
        clean_path.parent.mkdir(parents=True, exist_ok=True)
        clean_path.write_text(cleaned, encoding="utf-8")
        reduction  = round(100 * (1 - len(cleaned) / max(1, len(markdown))))
        emit("clean", "done", f"Cleaning complete — {reduction}% reduction",
             {"chars": len(cleaned), "reduction_pct": reduction, "slug": slug})

        # ── Stage 4: Chunk ────────────────────────────────────────────────────
        emit("chunk", "running", "Chunking cleaned markdown…")
        chunk_cfg = cfg.get("chunking", {})
        chunker   = MarkdownChunker(
            max_tokens      = chunk_cfg.get("max_tokens", 512),
            chunk_overlap   = chunk_cfg.get("chunk_overlap", 0),
            min_chunk_tokens= chunk_cfg.get("min_chunk_tokens", 0),
        )
        chunks    = chunker.chunk(cleaned)

        chunks_data = {
            "filename": slug,
            "total_chunks": len(chunks),
            "chunk_config": {
                "max_tokens": chunk_cfg.get("max_tokens", 512),
                "chunk_overlap": chunk_cfg.get("chunk_overlap", 0),
            },
            "chunks": chunks,
        }
        chunks_path = CHUNKS_DIR / f"{slug}_chunks.json"
        chunks_path.parent.mkdir(parents=True, exist_ok=True)
        with open(chunks_path, "w", encoding="utf-8") as fh:
            json.dump(chunks_data, fh, indent=2, ensure_ascii=False)
        emit("chunk", "done", f"Chunking complete — {len(chunks)} chunks",
             {"total_chunks": len(chunks), "slug": slug})

        # ── Stage 5: Vectorize (Qdrant) ───────────────────────────────────────
        emit("vectorize", "running", "Embedding chunks and indexing in Qdrant…")
        vectorizer = MedicalVectorizer(config=cfg)
        vectorizer.run(str(CLEANED_DIR))
        emit("vectorize", "done", "Vectorization complete — collection updated",
             {"collection": vectorizer.collection_name, "slug": slug})

        # ── Stage 6: Knowledge Graph (Neo4j) ──────────────────────────────────
        emit("kg", "running", "Extracting triplets → Neo4j knowledge graph…")
        try:
            from scripts.build_knowledge_graph import KnowledgeGraphBuilder
            builder = KnowledgeGraphBuilder(cfg)
            try:
                total_triplets = builder.run(CHUNKS_DIR)
            finally:
                builder.close()
            emit("kg", "done", f"Knowledge graph built — {total_triplets} triplet(s) written",
                 {"triplets": total_triplets, "slug": slug})
        except Exception as kg_exc:
            # KG is best-effort: log but don't fail the whole pipeline
            log.warning("KG stage failed (non-fatal): %s", kg_exc)
            emit("kg", "skipped", f"KG skipped: {kg_exc}", {"slug": slug})

        emit("done", "done", "Pipeline finished successfully ✓", {"slug": slug})

    except Exception as exc:
        log.exception("Pipeline failed for slug=%s", slug)
        emit("error", "error", str(exc))


# ── Routes ────────────────────────────────────────────────────────────────────

@app.post("/api/ingest")
async def ingest_pdf(file: UploadFile = File(...)) -> StreamingResponse:
    """Upload a PDF and stream 5-stage pipeline progress as SSE."""
    slug    = Path(file.filename or "upload").stem
    content = await file.read()

    pdf_path = UPLOAD_DIR / (slug + ".pdf")
    pdf_path.write_bytes(content)

    queue: asyncio.Queue[dict] = asyncio.Queue()
    loop  = asyncio.get_event_loop()

    # Run pipeline in thread pool so it doesn't block the event loop
    loop.run_in_executor(None, _run_pipeline, pdf_path, slug, queue, loop)

    async def event_stream() -> AsyncIterator[bytes]:
        while True:
            event = await queue.get()
            yield _sse_line(event)
            # Only close on the terminal pipeline-level sentinels emitted as
            # emit("done", ...) or emit("error", ...) — NOT on per-stage "done" status.
            if event.get("stage") in ("done", "error"):
                yield b": end\n\n"
                break

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Slug": slug,
        },
    )


@app.get("/api/ingest/status")
async def ingest_status() -> JSONResponse:
    """List processed docs with per-stage artifact existence."""
    docs: list[dict] = []

    # Load KG progress — keys are "{slug}_chunks" stems
    kg_progress: dict = {}
    kg_progress_file = CHUNKS_DIR / ".kg_progress.json"
    if kg_progress_file.exists():
        try:
            kg_progress = json.loads(kg_progress_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Collect all slugs from any stage
    slugs: set[str] = set()
    for p in OCR_DIR.glob("*_ocr.json"):
        slugs.add(p.stem.removesuffix("_ocr"))
    for p in MARKDOWN_DIR.glob("*_converted.md"):
        slugs.add(p.stem.removesuffix("_converted"))
    for p in CLEANED_DIR.glob("*_cleaned.md"):
        slugs.add(p.stem.removesuffix("_cleaned"))
    for p in CHUNKS_DIR.glob("*_chunks.json"):
        slugs.add(p.stem.removesuffix("_chunks"))

    for slug in sorted(slugs):
        viz_dir   = OCR_DIR / slug / "debug_visualizations"
        ocr_pages = sorted(viz_dir.glob(f"{slug}_page_*_debug.png")) if viz_dir.exists() else []
        chunks_exist = (CHUNKS_DIR / f"{slug}_chunks.json").exists()
        kg_done = bool(kg_progress.get(f"{slug}_chunks"))
        docs.append({
            "slug": slug,
            "stages": {
                "ocr":       (OCR_DIR / f"{slug}_ocr.json").exists(),
                "convert":   (MARKDOWN_DIR / f"{slug}_converted.md").exists(),
                "clean":     (CLEANED_DIR / f"{slug}_cleaned.md").exists(),
                "chunk":     chunks_exist,
                "vectorize": chunks_exist,
                "kg":        kg_done,
            },
            "ocr_pages": len(ocr_pages),
        })

    return JSONResponse({"docs": docs})


@app.get("/api/ingest/artifacts/ocr-viz/{slug}/{page}")
async def ocr_viz(slug: str, page: int) -> FileResponse:
    """Serve an OCR debug visualization PNG for a specific page."""
    img_path = OCR_DIR / slug / "debug_visualizations" / f"{slug}_page_{page:03d}_debug.png"
    if not img_path.exists():
        raise HTTPException(status_code=404, detail=f"OCR viz not found: {img_path.name}")
    return FileResponse(img_path, media_type="image/png")


@app.get("/api/ingest/artifacts/markdown/{slug}")
async def artifact_markdown(slug: str) -> JSONResponse:
    """Return converted markdown content (truncated preview)."""
    path = MARKDOWN_DIR / f"{slug}_converted.md"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Markdown artifact not found")
    text = path.read_text(encoding="utf-8")
    return JSONResponse({"slug": slug, "chars": len(text), "preview": text[:4000]})


@app.get("/api/ingest/artifacts/clean/{slug}")
async def artifact_clean(slug: str) -> JSONResponse:
    """Return cleaned markdown content (truncated preview)."""
    path = CLEANED_DIR / f"{slug}_cleaned.md"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Clean artifact not found")
    text = path.read_text(encoding="utf-8")
    return JSONResponse({"slug": slug, "chars": len(text), "preview": text[:4000]})


@app.get("/api/ingest/artifacts/chunks/{slug}")
async def artifact_chunks(slug: str) -> JSONResponse:
    """Return chunk metadata and first 10 chunks."""
    path = CHUNKS_DIR / f"{slug}_chunks.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Chunks artifact not found")
    data = json.loads(path.read_text(encoding="utf-8"))
    # Return metadata + first 10 sample chunks (keep response small)
    return JSONResponse({
        "slug":          slug,
        "total_chunks":  data.get("total_chunks", 0),
        "chunk_config":  data.get("chunk_config", {}),
        "sample_chunks": data.get("chunks", [])[:10],
    })


@app.get("/api/ingest/artifacts/kg-graph/{slug}")
async def artifact_kg_graph(slug: str) -> JSONResponse:
    """Return all Neo4j triplets for this document as D3 force-graph {nodes, links}."""
    cfg = load_ingestion_config(_CONFIG_PATH)
    neo4j_cfg = cfg.get("neo4j", {})
    uri      = neo4j_cfg.get("uri",      "bolt://localhost:7687")
    user     = neo4j_cfg.get("user",     "neo4j")
    password = neo4j_cfg.get("password", "neo4j")

    # Expand env vars (config uses ${VAR} syntax)
    import os
    uri      = os.path.expandvars(uri)
    user     = os.path.expandvars(user)
    password = os.path.expandvars(password)

    source_key = f"{slug}_chunks"   # matches r.source written by GraphCreator
    cypher = """
        MATCH (h:Entity)-[r]->(t:Entity)
        WHERE r.source = $source
        RETURN h.name AS head, type(r) AS relation,
               t.name AS tail, r.tier AS tier
        LIMIT 300
    """
    try:
        from neo4j import GraphDatabase as _GDB
        driver = _GDB.driver(uri, auth=(user, password))
        with driver.session() as session:
            records = list(session.run(cypher, source=source_key))
        driver.close()
    except Exception as exc:
        log.warning("KG graph query failed: %s", exc)
        return JSONResponse({"slug": slug, "nodes": [], "links": [], "error": str(exc)})

    node_map: dict[str, dict] = {}
    links: list[dict] = []
    for r in records:
        head, rel, tail, tier = r["head"], r["relation"], r["tail"], r.get("tier", 2)
        for name in (head, tail):
            if name not in node_map:
                node_map[name] = {"id": name, "label": name, "tier": int(tier or 2)}
        links.append({"source": head, "target": tail,
                       "relation": rel, "label": rel.replace("_", " ").title(),
                       "tier": int(tier or 2)})

    return JSONResponse({
        "slug":  slug,
        "nodes": list(node_map.values()),
        "links": links,
    })


@app.get("/api/ingest/artifacts/pdf")
async def serve_source_pdf(source: str) -> FileResponse:
    """Serve a source PDF by name for the provenance viewer.

    `source` may be a bare filename (e.g. 'study.pdf') or a relative path.
    Searches UPLOAD_DIR and data/pdfs/raw/ for the matching file.
    """
    raw_name = Path(source).name

    # Normalise: if source is a legacy _cleaned.md artifact name, derive the PDF slug.
    # e.g. "doc_cleaned.md" → "doc.pdf"
    if raw_name.endswith("_cleaned.md"):
        raw_name = raw_name[: -len("_cleaned.md")] + ".pdf"
    elif not raw_name.lower().endswith(".pdf"):
        raw_name = Path(raw_name).stem + ".pdf"

    search_dirs = [
        UPLOAD_DIR,
        _REPO_ROOT / "data" / "pdfs" / "raw",
    ]
    for search_dir in search_dirs:
        if search_dir.exists():
            for pdf_path in search_dir.rglob(raw_name):
                if pdf_path.is_file() and pdf_path.suffix.lower() == ".pdf":
                    return FileResponse(
                        str(pdf_path),
                        media_type="application/pdf",
                        headers={"Access-Control-Allow-Origin": "*"},
                    )
    raise HTTPException(status_code=404, detail=f"PDF not found: {source}")
