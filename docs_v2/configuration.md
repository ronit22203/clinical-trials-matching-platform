# Configuration Reference

All platform behaviour is controlled by `config/app.yaml`. This file is the single non-secret source of truth. Secrets are never stored here — all sensitive values are environment variable references in the form `${VAR_NAME}`, resolved at runtime.

Pydantic v2 validates every field at load time. A misconfigured file produces a field-level error with the exact key path before any service starts.

---

## Services

```yaml
services:
  neo4j:
    uri: ${NEO4J_URI}          # bolt://localhost:7687
    user: ${NEO4J_USER}        # neo4j
    database: neo4j

  qdrant:
    url: ${QDRANT_URL}         # http://localhost:6333
    collection: medical_papers

  temporal:
    host: ${TEMPORAL_HOST}     # localhost:7233
```

---

## Data Ingestion

### Directory layout

```yaml
data_ingestion:
  project_root: .
  input_dir: ../data/pdfs
  output:
    ocr_dir:      ../data/artifacts/extract
    markdown_dir: ../data/artifacts/convert
    cleaned_dir:  ../data/artifacts/clean
    chunks_dir:   ../data/artifacts/chunk
```

### OCR

```yaml
  ocr:
    langs: [en]
    device: mps                   # mps | cuda | cpu
    det_batch_size: 2
    rec_batch_size: 16
    image_scale: 2                # upscale factor; higher = better accuracy on small text
    confidence_threshold: 0.8     # lines below this score are discarded
    save_debug_images: true       # annotated images written to extract/debug/
    max_pages: null               # integer to limit pages per document; null = no limit
```

### Conversion

```yaml
  conversion:
    infer_headers: true
    preserve_spacing: true
    paragraph_gap_multiplier: 2.0
    bold_header_max_chars: 50     # lines longer than this are not promoted to headers
```

### Cleaning

```yaml
  cleaning:
    remove_phantom_links: true
    remove_images: true
    linearize_tables: true
    fix_hyphenation: true
    collapse_whitespace: true
    remove_pii: true
    fail_safe_on_pii_error: true
    language: en
    pii_entities:
      - EMAIL_ADDRESS
      - SG_NRIC
    pii_replacements:
      DEFAULT:       <REDACTED>
      EMAIL_ADDRESS: <EMAIL>
      SG_NRIC:       <NRIC_ID>
    custom_recognizers:
      - entity: SG_NRIC
        regex: (?i)[STFG]\d{7}[A-Z]
        score: 1.0
```

**Note:** `PHONE_NUMBER` is excluded from `pii_entities` by design. Scientific measurement intervals (e.g. `0.899–0.904`) match the phone number pattern and produce false positives in preprint corpora.

### Chunking

```yaml
  chunking:
    max_tokens: 500
    chunk_overlap: 50
    min_chunk_tokens: 20
    headers_to_split: ['#', '##', '###']  # treated as hard split boundaries
    respect_atomic_blocks: true            # never split code blocks or tables
```

### Vectorisation

```yaml
  vectorization:
    model_name: BAAI/bge-small-en-v1.5
    embedding_dim: 384
    device: cpu
    normalize_embeddings: false
    distance_metric: cosine
    qdrant_url: ${QDRANT_URL}
    collection_name: medical_papers
    batch_size: 64
```

### Knowledge Graph Extraction

```yaml
  knowledge_graph:
    enabled: true
    model: qwen3-8b                          # LM Studio model identifier (case-sensitive)
    chat_url: ${LM_STUDIO_BASE_URL}/chat/completions
    max_retries: 2
    timeout_seconds: 180
    max_tokens: 768
    max_text_chars: 1500                     # chunk text is truncated to this length before prompting
    min_chunk_chars: 50                      # chunks shorter than this are skipped
```

**Model identifier:** Must exactly match the model name as shown in LM Studio's model list. The string is case-sensitive. Example: `qwen3-8b`, not `Qwen3-8B` or `qwen3:8b`.

### Retrieval

```yaml
  retrieval:
    default_limit: 3       # number of chunks returned per query
    hybrid_search: true    # combine Qdrant vector search with Neo4j graph traversal
```

### Pipeline behaviour

```yaml
  pipeline:
    skip_existing: false   # set true to skip documents already processed in a previous run
    max_retries: 1
    parallel_workers: 1
```

### Logging

```yaml
  logging:
    level: INFO
    save_artifacts: true
    console_level: INFO
    file_level: DEBUG
    max_size_mb: 50
    backup_count: 3
```

---

## Data Acquisition

```yaml
data_acquisition:
  defaults:
    storage_mode: local
    default_source: medrxiv
    default_limit: 5
    output_dir: ../../data/pdfs
```

### Sources

Each source entry under `data_acquisition.sources` controls a fetcher:

```yaml
  sources:
    medrxiv:
      name: medrxiv
      enabled: true
      api:
        base_url: https://api.biorxiv.org
        timeout_seconds: 60
        max_retries: 3
```

### Storage providers

```yaml
  storage:
    providers:
      - name: s3
        priority: 1
        bucket: ${S3_BUCKET}
        region: ${AWS_REGION}
        retry:
          max_attempts: 3
          backoff_seconds: 2
      - name: azure
        priority: 2
        container: ${AZURE_CONTAINER}
        retry:
          max_attempts: 3
          backoff_seconds: 2
      - name: local
        priority: 99
        base_path: ../../data/pdfs
```

The `MultiCloudStorageManager` attempts providers in ascending priority order. A provider that accumulates consecutive failures is skipped until it recovers.

---

## Agentic Reasoning

### Defaults

```yaml
agentic_reasoning:
  defaults:
    default_agent: local_assistant
    model: lmstudio/qwen3-8b
    embed_model: text-embedding-nomic-embed-text-v1.5
    max_tokens: 4096
    temperature: 0.1
    tools_enabled:
      - graphrag
      - mcp_filesystem
```

### Agent definitions

Each entry under `agentic_reasoning.agents` is a named agent:

```yaml
  agents:
    <agent_key>:
      name: Human-readable name
      model: lmstudio/<model-id>        # or sglang/<org/model>
      system_prompt: |
        ...
      model_params:
        temperature: 0.1
        max_tokens: 4096
        top_p: 0.9
        frequency_penalty: 0.0
        presence_penalty: 0.0
      tools:
        - name: graphrag
        - name: pubmed_search
```

**Do not add `response_format` to `model_params`.** LM Studio only accepts `json_schema` or `text`. The agent does not require structured output — it uses tool-calling messages, not JSON mode.

### Tool definitions

Each entry under `agentic_reasoning.tools` registers a tool:

```yaml
  tools:
    <tool_key>:
      name: tool_key
      description: Single sentence used verbatim as the tool description in the LLM prompt.
      type: api
      module: src.tools.implementations.<module>
      class_name: <ClassName>
      config:
        base_url: https://api.example.com
        timeout: 10
        limit: 5
      auth:
        type: api_key           # api_key | none | oauth
        key: ENV_VAR_NAME       # environment variable holding the key — not the key itself
      rate_limit:
        calls_per_minute: 100
      enabled: true             # set false to disable without removing the entry
```

---

## Environment Variables

All environment variables are referenced in `config/app.yaml` via `${VAR_NAME}` syntax. Set them in the appropriate `.env` file for each module.

| Variable | Required by | Description |
|----------|-------------|-------------|
| `NEO4J_URI` | ingestion, reasoning | Bolt connection string, e.g. `bolt://localhost:7687` |
| `NEO4J_USER` | ingestion, reasoning | Neo4j username |
| `NEO4J_PASSWORD` | ingestion | Neo4j password |
| `QDRANT_URL` | ingestion, reasoning | Qdrant HTTP URL, e.g. `http://localhost:6333` |
| `TEMPORAL_HOST` | reasoning | Temporal server address, e.g. `localhost:7233` |
| `LM_STUDIO_BASE_URL` | ingestion (KG), reasoning | LM Studio OpenAI-compatible base URL, e.g. `http://localhost:1234/v1` |
| `AWS_ACCESS_KEY_ID` | acquisition | S3 access key (optional — enables S3 storage provider) |
| `AWS_SECRET_ACCESS_KEY` | acquisition | S3 secret key (optional) |
| `S3_BUCKET` | acquisition | Target S3 bucket name (optional) |
| `AZURE_STORAGE_CONNECTION_STRING` | acquisition | Azure Blob connection string (optional) |
| `NEXT_PUBLIC_API_URL` | platform-ui | FastAPI server URL, e.g. `http://localhost:8000` |
| `NEXT_PUBLIC_USE_MOCK` | platform-ui | Set `false` to use live API data |

---

## Changing Configuration

1. Edit `config/app.yaml`
2. For ingestion changes: re-run `make ingest` — the pipeline is deterministic and will rebuild affected artefacts
3. For agent changes: the FastAPI server reads config at startup — restart with `make serve-api`
4. For acquisition changes: re-run `make fetch`

No source code changes are required for any behavioural change expressible in YAML.
