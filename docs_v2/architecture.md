# System Architecture

## Overview

The Clinical Trials Matching Platform is a local-first, open-source system for clinical research intelligence. It ingests medical preprints and clinical documents, builds a hybrid knowledge graph and vector index over them, then exposes an agentic query interface for clinicians and researchers.

No patient data leaves the host. All inference runs locally via LM Studio or Ollama. All persistence is Docker-managed on the local filesystem.

---

## Module Topology

```
┌─────────────────────────────────────────────────────────────────────┐
│                        data-acquisition                             │
│  medRxiv · bioRxiv · PubMed · ClinicalTrials.gov                   │
│  PDF fetcher with multi-cloud fallback (S3 → Azure → local)        │
└────────────────────────┬────────────────────────────────────────────┘
                         │ raw PDFs → data/pdfs/
                         ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        data-ingestion                               │
│  Stage 1: OCR          (Surya, MPS/CPU)                            │
│  Stage 2: Conversion   (raw text → Markdown)                       │
│  Stage 3: Cleaning     (PII redaction, table linearisation)        │
│  Stage 4: Chunking     (token-aware, header-respecting)            │
│  Stage 5: Vectorisation (BGE-small-en-v1.5 → Qdrant)              │
│  Stage 6: KG Extraction (local LLM → Neo4j triplets)              │
└────────────┬────────────────────────────┬───────────────────────────┘
             │ Qdrant vectors             │ Neo4j triplets
             ▼                            ▼
┌────────────────────────────────────────────────────────────────────┐
│                      agentic-reasoning                             │
│  Runtime A: LangGraph ReAct   (low-latency, interactive)          │
│  Runtime B: Temporal Workflow (durable, auditable, HITL)          │
│  Tools: GraphRAG · PubMed · ClinicalTrials · FDA · Filesystem     │
│  API: FastAPI  /api/query  /api/health                            │
└────────────────────────────┬───────────────────────────────────────┘
                             │ JSON response
                             ▼
┌────────────────────────────────────────────────────────────────────┐
│                        platform-ui                                 │
│  Next.js 16 App Router · TypeScript                               │
│  Case view · Evidence panel · Reasoning trace · Audit trail       │
└────────────────────────────────────────────────────────────────────┘
```

---

## Data Flow (End-to-End)

1. **Acquisition** — Fetches PDFs from public repositories. Provider chain: S3 (priority 1) → Azure Blob (priority 2) → local disk (fallback). Multi-source search runs concurrently.

2. **Ingestion** — Five deterministic stages transform raw PDFs into queryable structures:
   - `OCR` produces per-page text with layout coordinates
   - `Conversion` reconstructs document structure as Markdown
   - `Cleaning` applies PII redaction (Presidio) and normalises formatting
   - `Chunking` splits documents into 500-token chunks with 50-token overlap, respecting section headers as natural boundaries
   - `Vectorisation` embeds each chunk with BGE-small-en-v1.5 and upserts into Qdrant

3. **KG Extraction** — A local instruction-following LLM (Qwen3-8B via LM Studio) extracts `(head, relation, tail)` medical triplets from each chunk and writes them to Neo4j as typed relationships.

4. **Retrieval** — `HybridRetriever` executes a Qdrant vector search and a Neo4j graph traversal concurrently, then merges and re-ranks results. Used by the `graphrag` tool inside the agent.

5. **Reasoning** — The agent receives a natural language query, selects tools (GraphRAG, PubMed, ClinicalTrials.gov, FDA, Filesystem), executes them—in parallel under Temporal or via `asyncio.gather` under LangGraph—and synthesises a structured response.

6. **Presentation** — The Next.js UI submits queries to the FastAPI server, receives a `QueryResponse` (synthesis + execution log + tool results), and renders evidence, reasoning trace, and execution metadata.

---

## Infrastructure Services

| Service | Image | Port | Role |
|---------|-------|------|------|
| Neo4j | `neo4j:5` | `7474` (HTTP), `7687` (Bolt) | Knowledge graph storage |
| Qdrant | `qdrant/qdrant:latest` | `6333` (HTTP), `6334` (gRPC) | Vector store |
| Temporal | `temporalio/auto-setup:latest` | `7233` | Durable workflow engine |
| Temporal UI | `temporalio/ui:latest` | `8080` | Workflow observability |
| PostgreSQL | `postgres:13` | internal | Temporal persistence backend |
| LM Studio | host process | `1234` | Local LLM inference server |

All services except LM Studio are Docker-managed. Configuration is in `docker-compose.local.yml`.

---

## Configuration Architecture

All runtime behaviour is defined in `config/app.yaml`. Source code is infrastructure; YAML is policy.

```
config/
└── app.yaml          # single non-secret source of truth
    ├── services       # Neo4j, Qdrant, Temporal URIs (env-var references)
    ├── data_ingestion # pipeline stages, PII rules, chunking params, embedding model
    ├── data_acquisition # sources, storage providers, retry settings
    └── agentic_reasoning
        ├── agents     # named agent configs (model, system prompt, tools)
        └── tools      # tool registry (module, class, API config, auth)
```

Pydantic v2 validates all YAML fields at load time. A misconfigured file produces field-level errors before any execution begins.

Secrets are never stored in YAML. All sensitive values are environment variable references (`${VAR}`) resolved at runtime.

---

## Execution Runtimes

Two execution paths share the same agent configuration and tool registry:

### LangGraph ReAct

- Invoked via `make reasoning-run-query` or `POST /api/query` with `mode: langgraph`
- LLM autonomously selects and calls tools via `create_react_agent`
- Tool calls execute concurrently via `asyncio.gather`
- Suitable for low-latency interactive queries

### Temporal Workflow

- Invoked via `make reasoning-temporal-run` or `mode: temporal`
- `ClinicalResearchWorkflow` is a durable, deterministic workflow registered with Temporal
- All tool calls are `@activity.defn` functions executed by a worker process
- Full audit trail: every activity input/output is persisted in Temporal's PostgreSQL store
- Supports Human-in-the-Loop (HITL) gate: workflow pauses at a `@workflow.signal` checkpoint pending external approval

### Determinism Constraint

`workflows.py` must remain deterministic. No I/O, logging, `random`, `time`, or non-deterministic calls inside `@workflow.run`. All side effects go in `activities.py`.

---

## Tool Plugin System

Adding a tool requires exactly two artefacts:

1. **Implementation** — `agentic-reasoning/src/tools/implementations/<tool>.py`
   Subclass `BaseTool`, implement `execute(self, input: Any) -> Any`.

2. **Registration** — `config/app.yaml` under `agentic_reasoning.tools`
   ```yaml
   my_tool:
     module: src.tools.implementations.my_tool
     class_name: MyTool
     config: { ... }
     auth: { type: api_key, key: MY_API_KEY_ENV_VAR }
     enabled: true
   ```

`ToolRegistry` loads definitions at startup. A tool that fails to import or initialise does not prevent others from loading (fault-isolated).

`BaseTool` provides a `TTLCache` via `cached_execute()`. Prefer this over `execute()` for repeated identical queries.

---

## GraphRAG Retrieval

`HybridRetriever` combines two retrieval signals:

| Signal | Mechanism | Weight |
|--------|-----------|--------|
| Semantic similarity | Qdrant cosine search over BGE-small-en-v1.5 embeddings | Primary |
| Graph proximity | Neo4j depth-2 traversal from seed entities | Secondary |

Results are merged, deduplicated, and returned as ranked context chunks. The `graphrag` tool wraps this retriever. The agent synthesis prompt explicitly weights internal knowledge-base results as primary evidence over public API results.

---

## Security Posture

- **No external inference calls**: all LLM inference is local (LM Studio / Ollama)
- **PII redaction at ingestion time**: `EMAIL_ADDRESS`, `SG_NRIC` entities are replaced before any chunk is stored or embedded
- **No hardcoded credentials**: all secrets are environment variables, never committed to source
- **Audit trail**: Temporal persists every tool call input/output; FastAPI logs every query with a UUID execution ID
