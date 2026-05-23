# Backend Endpoints Reference

Two operational surfaces: **Query & Retrieval** and **Ingestion Pipeline**. All endpoints are served under `http://localhost:8000`.

---

## TypeScript Types

```typescript
type Result = {
  id: string;
  trial_id: string;
  title: string;
  snippet: string;
  relevance_score: number;          // 0.0 – 1.0
  provenance: Provenance[];
  matched_criteria: string[];
};

type Provenance = {
  source_document: string;
  byte_range: [number, number];     // [start, end] byte offsets in source PDF
  highlighted_text: string;
  confidence_score: number;
};

type KGNode = {
  id: string;
  label: string;
  type: "trial" | "condition" | "intervention" | "outcome" | "document";
  metadata?: Record<string, any>;
};

type KGEdge = {
  source: string;                   // KGNode.id
  target: string;                   // KGNode.id
  label: string;
  weight?: number;
};

type ScoreBreakdown = {
  top_hits: { doc_id: string; score: number }[];
  avg_score: number;
  method: "bm25" | "dense";
};

type FusionDetails = {
  strategy: "rrf" | "weighted_sum";
  weights: { bm25: number; dense: number };
  final_scores: { doc_id: string; score: number }[];
};

type StepProgress = {
  step: "ocr" | "convert" | "clean" | "chunk" | "vectorize";
  status: "pending" | "processing" | "completed" | "failed";
  progress: number;                 // 0.0 – 1.0
  message: string;
  started_at?: string;              // ISO 8601
  completed_at?: string;
};

type Chunk = {
  chunk_id: string;
  text: string;
  section_title: string;
  depth: number;
  parent_id: string | null;
  char_start: number;
  char_end: number;
  metadata: Record<string, any>;
};

type OCRPage = {
  page_number: number;
  width: number;
  height: number;
  blocks: {
    text: string;
    confidence: number;
    bbox: [number, number, number, number];   // [x0, y0, x1, y1] in pixels
  }[];
};
```

---

## A. Query & Retrieval Endpoints

### `POST /api/query`

Submit a natural language query for clinical trial matching. Returns immediately with a `query_id`; retrieve results via polling or streaming.

#### Request

```
Content-Type: application/json
```

```json
{
  "query": "string",
  "top_k": 10,
  "rerank": true,
  "filters": {
    "condition": "string",
    "phase": "string",
    "status": "string"
  }
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `query` | `string` | Yes | — | Natural language query. 1–4096 characters. |
| `top_k` | `integer` | No | `10` | Maximum number of results to return. |
| `rerank` | `boolean` | No | `true` | Apply CrossEncoder reranker to retrieved chunks. |
| `filters` | `object` | No | `{}` | Optional metadata filters applied before vector search. |

#### Response `200 OK`

```json
{
  "query_id": "3f8a1c2d-...",
  "status": "processing",
  "estimated_time": 4.2
}
```

| Field | Type | Description |
|-------|------|-------------|
| `query_id` | `string (UUID)` | Stable identifier for this query execution. Use with all `/api/query/{query_id}/*` endpoints. |
| `status` | `"processing"` | Always `"processing"` on initial submission. |
| `estimated_time` | `number \| null` | Estimated seconds to completion based on recent query latencies. Null if no baseline is available. |

#### Response `422 Unprocessable Entity`

```json
{
  "detail": [{ "loc": ["body", "query"], "msg": "String should have at least 1 character", "type": "string_too_short" }]
}
```

---

### `GET /api/query/{query_id}/results`

Poll for or stream results of a previously submitted query. Safe to call repeatedly until `status` is `"completed"` or `"failed"`.

#### Path Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `query_id` | `string (UUID)` | Returned by `POST /api/query`. |

#### Response `200 OK`

```json
{
  "query_id": "3f8a1c2d-...",
  "status": "completed",
  "results": [
    {
      "id": "result_01",
      "trial_id": "NCT04280705",
      "title": "Efficacy of Drug X in Stage III NSCLC",
      "snippet": "...patients with confirmed EGFR mutation showed...",
      "relevance_score": 0.94,
      "provenance": [
        {
          "source_document": "nct04280705_protocol.pdf",
          "byte_range": [14200, 14380],
          "highlighted_text": "patients with confirmed EGFR mutation",
          "confidence_score": 0.91
        }
      ],
      "matched_criteria": ["EGFR mutation", "Stage III", "NSCLC"]
    }
  ],
  "error": null
}
```

| Field | Type | Description |
|-------|------|-------------|
| `status` | `"completed" \| "processing" \| "failed"` | Current execution state. |
| `results` | `Result[] \| null` | Present only when `status === "completed"`. |
| `error` | `string \| null` | Non-null only when `status === "failed"`. |

#### Response `404 Not Found`

Returned when `query_id` does not exist or has expired.

```json
{ "detail": "Query not found: 3f8a1c2d-..." }
```

---

### `GET /api/query/{query_id}/provenance`

Byte-level provenance for a specific result — links a retrieved snippet back to its exact location in the source PDF.

#### Query Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `result_id` | `string` | Yes | The `id` field from a `Result` object. |

#### Response `200 OK`

```json
{
  "result_id": "result_01",
  "source_document": "nct04280705_protocol.pdf",
  "byte_range": [14200, 14380],
  "highlighted_text": "patients with confirmed EGFR mutation showed a 62% response rate",
  "confidence_score": 0.91
}
```

| Field | Description |
|-------|-------------|
| `source_document` | Filename of the source PDF in `data/pdfs/raw/`. |
| `byte_range` | `[start, end]` byte offsets into the **cleaned Markdown** artifact at `data/artifacts/clean/`. Use to reconstruct the passage without re-reading the PDF. |
| `highlighted_text` | Verbatim text at the provenance location, post-cleaning. |
| `confidence_score` | CrossEncoder or cosine similarity score for this specific passage. |

---

### `GET /api/query/{query_id}/knowledge-graph`

Returns the live Neo4j subgraph built from documents retrieved for this query — nodes and directed edges in a format ready for D3/Cytoscape rendering.

#### Response `200 OK`

```json
{
  "nodes": [
    { "id": "n_001", "label": "NCT04280705", "type": "trial", "metadata": { "phase": "III", "status": "recruiting" } },
    { "id": "n_002", "label": "NSCLC", "type": "condition", "metadata": {} },
    { "id": "n_003", "label": "EGFR inhibitor", "type": "intervention", "metadata": {} }
  ],
  "edges": [
    { "source": "n_001", "target": "n_002", "label": "TREATS", "weight": 0.87 },
    { "source": "n_001", "target": "n_003", "label": "USES_INTERVENTION", "weight": 0.92 }
  ],
  "query_focus_node": "n_001"
}
```

| Field | Description |
|-------|-------------|
| `nodes` | All entity nodes present in the retrieved subgraph. `type` maps to the Neo4j node label. |
| `edges` | Directed `(source)-[label]->(target)` triples extracted by `build_knowledge_graph.py`. |
| `query_focus_node` | `KGNode.id` of the node most semantically central to the query, for rendering focus. Null if indeterminate. |

---

### `GET /api/query/{query_id}/retrieval-details`

Hybrid retrieval breakdown showing the per-method contribution of BM25, dense vector search, and their fusion for this query.

#### Response `200 OK`

```json
{
  "bm25": {
    "top_hits": [
      { "doc_id": "nct04280705_protocol", "score": 14.3 }
    ],
    "avg_score": 9.1,
    "method": "bm25"
  },
  "dense": {
    "top_hits": [
      { "doc_id": "nct04280705_protocol", "score": 0.91 }
    ],
    "avg_score": 0.74,
    "method": "dense"
  },
  "fusion": {
    "strategy": "rrf",
    "weights": { "bm25": 0.4, "dense": 0.6 },
    "final_scores": [
      { "doc_id": "nct04280705_protocol", "score": 0.95 }
    ]
  }
}
```

BM25 scores are unnormalised term-frequency values. Dense scores are cosine similarities in `[0, 1]`. Fusion scores are the output of Reciprocal Rank Fusion (RRF) or weighted sum depending on `config/app.yaml → graphrag.fusion_strategy`.

---

## B. Ingestion Pipeline Endpoints

### `POST /api/ingest`

Start ingestion of a clinical trial document. Returns an SSE stream that emits progress events as each pipeline stage executes.

#### Request

```
Content-Type: multipart/form-data
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file` | `File` | Yes | PDF file to ingest. Max 100 MB. |
| `source_id` | `string` | No | Caller-supplied stable identifier (e.g. NCT number). Defaults to file stem. |
| `skip_stages` | `string` | No | Comma-separated stage names to skip: `ocr`, `convert`, `clean`, `chunk`, `vectorize`. |

#### SSE Stream

```
Content-Type: text/event-stream
Cache-Control: no-cache
```

Events are emitted in order as each pipeline stage progresses. The stream closes after the `complete` or `error` terminal event.

```
event: progress
data: {"step": "ocr", "progress": 0.0, "status": "processing", "message": "Starting OCR on 12 pages..."}

event: progress
data: {"step": "ocr", "progress": 0.45, "status": "processing", "message": "Processing page 3/12..."}

event: progress
data: {"step": "ocr", "progress": 1.0, "status": "completed", "message": "OCR complete. 12 pages extracted."}

event: progress
data: {"step": "chunking", "progress": 0.8, "status": "processing", "message": "Created chunk 47/60..."}

event: chunk_completed
data: {"chunk_id": "chunk_12", "text": "EGFR mutation patients...", "metadata": {"section": "Results", "depth": 2}}

event: error
data: {"step": "ocr", "message": "Failed to process page 7", "recoverable": true}

event: complete
data: {"job_id": "abc123", "total_chunks": 60, "processing_time": 12.4}
```

**Event types:**

| Event | When emitted | Key fields |
|-------|-------------|------------|
| `progress` | Continuously during each stage | `step`, `progress` (0–1), `status`, `message` |
| `chunk_completed` | After each chunk is finalised in Stage 4 | `chunk_id`, `text`, `metadata` |
| `error` | On recoverable or fatal stage failure | `step`, `message`, `recoverable` |
| `complete` | Pipeline finished successfully | `job_id`, `total_chunks`, `processing_time` |

When `recoverable: true`, the pipeline continues. When `recoverable: false`, subsequent stages are skipped and the stream closes.

---

### `GET /api/ingest/{job_id}/status`

Check the current status and per-stage progress of an ingestion job. Safe to poll.

#### Response `200 OK`

```json
{
  "job_id": "abc123",
  "status": "processing",
  "progress": [
    { "step": "ocr",      "status": "completed", "progress": 1.0,  "message": "12 pages extracted.",    "started_at": "2026-05-22T14:01:00Z", "completed_at": "2026-05-22T14:01:08Z" },
    { "step": "convert",  "status": "completed", "progress": 1.0,  "message": "Markdown generated.",    "started_at": "2026-05-22T14:01:08Z", "completed_at": "2026-05-22T14:01:09Z" },
    { "step": "clean",    "status": "processing","progress": 0.3,  "message": "Removing artifacts...",  "started_at": "2026-05-22T14:01:09Z", "completed_at": null },
    { "step": "chunk",    "status": "pending",   "progress": 0.0,  "message": "",                       "started_at": null, "completed_at": null },
    { "step": "vectorize","status": "pending",   "progress": 0.0,  "message": "",                       "started_at": null, "completed_at": null }
  ]
}
```

`status` at the top level reflects the most advanced stage: `pending | processing | completed | failed`.

---

### `GET /api/ingest/{job_id}/debug/ocr`

Returns raw OCR output with per-block bounding boxes and confidence scores. Used to validate OCR quality before downstream stages.

#### Response `200 OK`

```json
{
  "pages": [
    {
      "page_number": 1,
      "width": 2480,
      "height": 3508,
      "blocks": [
        {
          "text": "CLINICAL STUDY PROTOCOL",
          "confidence": 0.99,
          "bbox": [214, 148, 1080, 192]
        },
        {
          "text": "A Phase III, Randomised, Double-Blind...",
          "confidence": 0.96,
          "bbox": [214, 220, 2266, 264]
        }
      ]
    }
  ]
}
```

`bbox` is `[x0, y0, x1, y1]` in pixels at the resolution specified by `data_ingestion.ocr.image_scale` in `config/app.yaml` (default scale ×2 → 2× physical pixel dimensions). Blocks with confidence below `confidence_threshold` are excluded.

---

### `GET /api/ingest/{job_id}/chunks`

Returns all chunks produced by Stage 4 (`MarkdownChunker`), including hierarchy metadata and byte-range provenance.

#### Response `200 OK`

```json
{
  "chunks": [
    {
      "chunk_id": "chunk_00",
      "text": "Context: Protocol > Eligibility Criteria\n\nPatients must have confirmed EGFR exon 19 deletion...",
      "section_title": "Eligibility Criteria",
      "depth": 2,
      "parent_id": "chunk_00_parent",
      "char_start": 4820,
      "char_end": 5240,
      "metadata": {
        "source_document": "nct04280705_protocol",
        "token_count": 98
      }
    }
  ]
}
```

`text` includes the breadcrumb prefix (`"Context: A > B\n\n"`) exactly as stored in Qdrant. `char_start` / `char_end` are offsets into the cleaned Markdown artifact at `data/artifacts/clean/{doc_id}.md`.

---

### `GET /api/ingest/{job_id}/markdown`

Returns the cleaned Markdown output from Stage 3 and the log of cleaning operations applied.

#### Response `200 OK`

```json
{
  "markdown": "# Clinical Study Protocol\n\n## 1. Eligibility Criteria\n\n...",
  "cleaning_log": [
    "Removed 3 boilerplate headers",
    "Redacted 1 NRIC pattern ([STFG]\\d{7}[A-Z])",
    "Normalised 47 hyphenated line breaks",
    "Stripped 2 page-number footers"
  ]
}
```

`cleaning_log` entries correspond to operations performed by `TextCleaner` in `data-ingestion/src/processors/cleaner.py`. PII redaction entries are logged here when `cleaning.remove_pii: true` in `config/app.yaml`.

---

## curl Examples

```bash
# Submit a query
curl -s -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"query": "EGFR mutation trials in Stage III NSCLC", "top_k": 5}' | jq .

# Poll for results
curl -s http://localhost:8000/api/query/3f8a1c2d-.../results | jq '{status, count: (.results | length)}'

# Byte-level provenance for result_01
curl -s "http://localhost:8000/api/query/3f8a1c2d-.../provenance?result_id=result_01" | jq .

# Knowledge graph for a completed query
curl -s http://localhost:8000/api/query/3f8a1c2d-.../knowledge-graph | jq '{nodes: (.nodes | length), edges: (.edges | length)}'

# Retrieval method breakdown
curl -s http://localhost:8000/api/query/3f8a1c2d-.../retrieval-details | jq .fusion

# Start ingestion (SSE stream)
curl -s -N -X POST http://localhost:8000/api/ingest \
  -F "file=@data/pdfs/raw/nct04280705_protocol.pdf" \
  -F "source_id=NCT04280705"

# Check ingestion job status
curl -s http://localhost:8000/api/ingest/abc123/status | jq '.progress[] | {step, status, progress}'

# Fetch OCR debug data for page 1
curl -s http://localhost:8000/api/ingest/abc123/debug/ocr | jq '.pages[0].blocks[:3]'

# List all chunks
curl -s http://localhost:8000/api/ingest/abc123/chunks | jq '.chunks | length'

# Get cleaned markdown
curl -s http://localhost:8000/api/ingest/abc123/markdown | jq '.cleaning_log'
```

---

## Error Codes

| HTTP Status | Meaning |
|-------------|---------|
| `200` | Success |
| `202` | Accepted (job enqueued, not yet started) |
| `404` | `query_id` or `job_id` not found / expired |
| `409` | Duplicate `source_id` — document already ingested; re-ingest with `?force=true` |
| `413` | PDF exceeds 100 MB limit |
| `422` | Request body validation failure (Pydantic) |
| `500` | Unhandled server error — check `agentic-reasoning/log/` or `data/artifacts/ingestion.log` |
