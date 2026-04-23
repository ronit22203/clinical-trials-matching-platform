# Data Pipeline

The ingestion pipeline transforms raw PDFs into queryable vector and graph representations through six deterministic stages. Each stage reads from and writes to a well-defined directory under `data/artifacts/`.

---

## Stage Overview

```
data/pdfs/
    │
    ▼ Stage 1: OCR
data/artifacts/extract/       ← per-page text + layout coordinates
    │
    ▼ Stage 2: Conversion
data/artifacts/convert/       ← reconstructed Markdown
    │
    ▼ Stage 3: Cleaning
data/artifacts/clean/         ← PII-redacted, normalised Markdown
    │
    ▼ Stage 4: Chunking
data/artifacts/chunk/         ← JSON array of token-bounded chunks
    │
    ├─▼ Stage 5: Vectorisation
    │   Qdrant collection `medical_papers` ← BGE-small-en-v1.5 embeddings
    │
    └─▼ Stage 6: KG Extraction
        Neo4j database ← (head, relation, tail) medical triplets
```

---

## Stage 1 — OCR

**Tool:** Surya (deep learning OCR)  
**Config path:** `data_ingestion.ocr`

Surya processes each PDF page using a detection model followed by a recognition model. On Apple Silicon, inference runs on MPS; on CPU-only hosts, it falls back gracefully.

Key configuration parameters:

| Parameter | Default | Effect |
|-----------|---------|--------|
| `device` | `mps` | Inference device (`mps`, `cuda`, `cpu`) |
| `image_scale` | `2` | Upscale factor before OCR — higher values improve accuracy on small text |
| `confidence_threshold` | `0.8` | Lines below this score are discarded |
| `save_debug_images` | `true` | Saves annotated debug images to `extract/debug/` |
| `max_pages` | `null` | Set to an integer to limit pages per document (useful for large PDFs) |

Output: one JSON file per document containing all page-level text blocks with bounding boxes and confidence scores.

---

## Stage 2 — Conversion

**Tool:** custom Markdown converter  
**Config path:** `data_ingestion.conversion`

Reconstructs document structure from the OCR output. Heuristics infer section headers, detect bold text, and preserve paragraph spacing.

| Parameter | Default | Effect |
|-----------|---------|--------|
| `infer_headers` | `true` | Promotes short, bold lines to Markdown headers |
| `bold_header_max_chars` | `50` | Lines longer than this are not promoted to headers |
| `preserve_spacing` | `true` | Retains inter-paragraph whitespace |
| `paragraph_gap_multiplier` | `2.0` | Multiplier applied to average line height to detect paragraph breaks |

Output: one `.md` file per document.

---

## Stage 3 — Cleaning

**Tool:** Presidio (PII detection), custom normaliser  
**Config path:** `data_ingestion.cleaning`

Applies a sequence of normalisation passes and redacts personally identifiable information.

### Normalisation passes (applied in order)

| Pass | Controlled by |
|------|--------------|
| Remove phantom links (e.g. `[1]`, `[2]`) | `remove_phantom_links` |
| Remove embedded image references | `remove_images` |
| Linearise tables to pipe-delimited text | `linearize_tables` |
| Rejoin hyphenated line-break splits | `fix_hyphenation` |
| Collapse excess whitespace | `collapse_whitespace` |

### PII Redaction

Presidio scans each document for the entity types listed in `pii_entities`. Detected spans are replaced with the corresponding token from `pii_replacements`.

Default entity list:
- `EMAIL_ADDRESS` → `<EMAIL>`
- `SG_NRIC` → `<NRIC_ID>` (custom regex recogniser)

`PHONE_NUMBER` is intentionally excluded. The source corpus is public preprints — scientific measurement intervals (e.g. `0.899–0.904`) share the phone number pattern and produce false positives.

`fail_safe_on_pii_error: true` ensures that a Presidio failure on a single document does not abort the pipeline.

---

## Stage 4 — Chunking

**Config path:** `data_ingestion.chunking`

Splits the cleaned Markdown into token-bounded chunks suitable for embedding.

| Parameter | Default | Effect |
|-----------|---------|--------|
| `max_tokens` | `500` | Maximum tokens per chunk |
| `chunk_overlap` | `50` | Overlap between consecutive chunks (preserves cross-boundary context) |
| `min_chunk_tokens` | `20` | Chunks below this size are discarded |
| `headers_to_split` | `['#', '##', '###']` | Section boundaries are treated as hard splits |
| `respect_atomic_blocks` | `true` | Code blocks and tables are never split mid-way |

Output: one JSON file per document — an array of chunk objects, each containing `chunk_id`, `text`, `token_count`, `source_doc`, and `metadata`.

---

## Stage 5 — Vectorisation

**Model:** `BAAI/bge-small-en-v1.5` (384-dimensional, cosine metric)  
**Config path:** `data_ingestion.vectorization`

Each chunk is embedded and upserted into Qdrant. The collection name is `medical_papers` by default (configurable via `collection_name`).

| Parameter | Default | Notes |
|-----------|---------|-------|
| `embedding_dim` | `384` | Must match model output dimension |
| `distance_metric` | `cosine` | Qdrant collection metric |
| `batch_size` | `64` | Chunks embedded per batch — reduce if OOM |
| `normalize_embeddings` | `false` | Set `true` if the model does not self-normalise |

Each point in Qdrant stores the full chunk text and metadata in its payload, enabling retrieval without a separate document store.

---

## Stage 6 — KG Extraction

**Tool:** local LLM via LM Studio (Qwen3-8B)  
**Config path:** `data_ingestion.knowledge_graph`  
**Implementation:** `data-ingestion/src/processors/graph_creator.py`

Extracts `(head, relation, tail)` triplets from each chunk using a local chat-completions endpoint and writes them to Neo4j as typed relationships.

### Allowed relation types

`TREATS · CAUSES · PREVENTS · INHIBITS · INTERACTS_WITH · PREDICTS · MEASURED_BY · ASSOCIATED_WITH · REDUCES · INCREASES`

### Prompt design

A one-shot example is injected into every prompt to reduce zero-shot refusal rates on 7B models. The prompt uses a single `user` role message — no `system` role — to ensure compatibility with Mistral-family chat templates.

### JSON handling

`GraphCreator` auto-detects whether the LM Studio instance supports `response_format: json_schema`. If not (HTTP 400), it silently falls back to text mode with a regex-based JSON extractor.

The `_sanitize_json()` method:
1. Strips `<think>...</think>` chain-of-thought blocks (Qwen3)
2. Extracts the first complete `{...}` object using a bracket-depth tracker (handles nested objects)
3. Fixes trailing commas before `}` and `]`
4. If the response was truncated mid-token, `_repair_truncated_json()` discards the incomplete trailing object and closes all open brackets

### Neo4j schema

Entities are created as `(:Entity {name, type})` nodes. Relations are typed edges: `(head)-[:RELATION_TYPE]->(tail)`.

```cypher
-- Example: verify extraction ran
MATCH (a)-[r]->(b) RETURN a.name, type(r), b.name LIMIT 20
```

---

## Running the Pipeline

```bash
# Full pipeline on all PDFs
make ingest

# Cap document count
make ingest N=5

# Skip specific stages
make ingestion-run SKIP=ocr        # skip OCR (re-use existing extract/)
make ingestion-run SKIP=vectorize  # skip embedding

# KG extraction only (uses existing chunks)
make ingestion-neo4j-build
```

---

## Data Acquisition

PDFs are fetched by the `data-acquisition` module before ingestion.

```bash
make fetch SOURCE=medrxiv MAX_PDFS=10
make fetch SOURCE=pubmed  MAX_PDFS=5
make fetch SOURCE=biorxiv MAX_PDFS=5
```

### Storage provider chain

Providers are attempted in priority order. A provider with consecutive failures is marked degraded and skipped until it recovers.

| Priority | Provider | Activation |
|----------|----------|------------|
| 1 | AWS S3 | `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` set |
| 2 | Azure Blob | `AZURE_STORAGE_CONNECTION_STRING` set |
| 99 | Local disk | Always available (fallback) |

Provider priority and retry settings are defined in `config/app.yaml` under `data_acquisition.storage.providers`.

---

## Artifact Inspection

```bash
make ingestion-inspect                  # summary of all artifact directories
make ingestion-list-documents           # tracked document registry
make ingestion-neo4j-stats              # node and relationship counts
make ingestion-compare-runs DOC=<uuid> EXEC1=<uuid> EXEC2=<uuid>  # diff two runs
```
