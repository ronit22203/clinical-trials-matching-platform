# Agent Framework

## Overview

The `agentic-reasoning` module implements a LangGraph-based agent framework. The same agent configuration and tool registry drive an interactive ReAct loop, with optional concurrent tool fan-out via `run_parallel()` when deterministic prefetch is preferred.

---

## Agent Configuration

Agents are defined in `config/app.yaml` under `agentic_reasoning.agents`. Each entry is a named agent configuration:

```yaml
agentic_reasoning:
  agents:
    local_assistant:
      name: Local Clinical Research Assistant
      model: lmstudio/qwen3-8b
      system_prompt: |
        You are a clinical research assistant with access to a local
        knowledge base and filesystem tools...
      model_params:
        temperature: 0.1
        max_tokens: 4096
        top_p: 0.9
        frequency_penalty: 0.0
        presence_penalty: 0.0
      tools:
        - name: graphrag
        - name: mcp_filesystem
```

### Built-in agents

| Agent key | Model | Tools | Use case |
|-----------|-------|-------|----------|
| `local_assistant` | Qwen3-8B (LM Studio) | GraphRAG, Filesystem | Local-only, no internet required |
| `assistant` | Qwen3-8B (LM Studio) | GraphRAG, PubMed, ClinicalTrials, FDA, Filesystem | Full external API access |
| `sglang_assistant` | Qwen2.5-7B-Instruct (SGLang) | All tools | High-throughput SGLang backend |
| `mcp_test` | Qwen3-8B | Filesystem only | MCP integration testing |

---

## Execution Runtime A — LangGraph ReAct

**Entry points:**
- CLI: `make reasoning-run-query QUERY="..."`
- API: `POST /api/query` with `mode: langgraph`

The agent uses LangGraph's `create_react_agent` with the configured LLM and LangChain-wrapped tools. The LLM autonomously selects tools based on the query and iterates until it produces a final synthesis.

Tool calls are dispatched concurrently:

```python
# agent.py — run_parallel()
tasks = [
    asyncio.to_thread(instance.cached_execute, query)
    for instance in selected_tools
]
tool_results = dict(await asyncio.gather(*tasks))
```

`asyncio.to_thread` bridges synchronous tool implementations into the async call chain without blocking the event loop.

**When to use:** Low-latency interactive queries, development, UI-backed sessions.

---

## Tool Plugin System

### Implementing a tool

Create `agentic-reasoning/src/tools/implementations/<tool_name>.py`:

```python
from ..base import BaseTool

class MyTool(BaseTool):
    name = "my_tool"
    description = "One sentence describing what this tool does and when to use it."

    def execute(self, input: str) -> str:
        # All HTTP calls, file I/O, or external queries go here.
        # Return a string — the agent receives this as tool output.
        result = call_some_api(input)
        return format_result(result)
```

Register in `config/app.yaml`:

```yaml
agentic_reasoning:
  tools:
    my_tool:
      name: my_tool
      description: One sentence describing what this tool does.
      type: api
      module: src.tools.implementations.my_tool
      class_name: MyTool
      config:
        base_url: https://api.example.com
        timeout: 10
      auth:
        type: api_key
        key: MY_TOOL_API_KEY   # environment variable name — not the value
      enabled: true
```

Add to an agent's tool list:

```yaml
agents:
  assistant:
    tools:
      - name: my_tool
```

### Fault isolation

`ToolRegistry` loads each tool definition independently. If a tool fails to import or initialise (missing dependency, invalid config), it logs a warning and continues loading the remaining tools. A single broken tool does not prevent the agent from starting.

### Caching

`BaseTool` provides a TTL-based cache via `cached_execute()`. Use it instead of `execute()` for queries that are likely to repeat within a session:

```python
result = tool_instance.cached_execute(query)  # returns cached result if available
```

---

## Built-in Tools

### `graphrag`

Hybrid retrieval over ingested documents.

- Executes a Qdrant cosine-similarity search and a Neo4j depth-2 graph traversal concurrently
- Merges and re-ranks results
- Returns top-k chunks as formatted context

**Input:** natural language query  
**Config:** `data_ingestion.retrieval.default_limit` controls result count

### `pubmed_search`

Queries the PubMed E-utilities API for peer-reviewed literature.

**Input:** condition, drug, or mechanism name  
**No authentication required**

### `clinical_trials`

Queries ClinicalTrials.gov v2 API for matching studies.

**Input:** condition, drug, or intervention name  
**Returns:** NCT ID, title, phase, status, sponsor, and brief summary  
**No authentication required**

### `fda_adverse_events`

Queries the FDA FAERS (adverse event reporting system) via openFDA.

**Input:** drug name  
**Returns:** top adverse reactions and safety report metadata  
**No authentication required** (rate-limited at 240 requests/minute)

### `mcp_filesystem`

Reads and writes files on the local filesystem via the Model Context Protocol.

**Input:** file path or natural language instruction (e.g. "read the file at /tmp/report.txt")  
**Use cases:** save synthesised reports, read local reference data

---

## FastAPI Server

The reasoning server exposes two endpoints.

### `POST /api/query`

Submit a query to the agent.

**Request body:**

```json
{
  "query": "string (1–4096 characters)",
  "tools": ["graphrag", "pubmed_search"],   // optional override
  "mode": "langgraph",                     // default: langgraph
  "agent_config": "local_assistant"         // optional agent override
}
```

**Response:**

```json
{
  "synthesis": "string",
  "executionLog": {
    "executionId": "uuid",
    "model": "lmstudio/qwen3-8b",
    "latencyMs": 4210.3,
    "toolsCalled": ["graphrag"],
    "tokensInput": 312,
    "tokensOutput": 487,
    "routerIntent": "langgraph",
    "entries": [ ... ]
  },
  "toolResults": {
    "graphrag": "Retrieved context text..."
  }
}
```

All field names are camelCase (serialised from Python snake_case via Pydantic `alias_generator`).

### `GET /api/health`

Liveness probe. Returns `{"status": "ok", "version": "0.1.0"}`.

---

## CLI Reference

```bash
# Interactive session (LangGraph)
make reasoning-run

# Single query (LangGraph)
make reasoning-run-query QUERY="What biomarkers predict sepsis mortality?"

# Start FastAPI server
make reasoning-serve-api

# Run test suite
make reasoning-test
```

### Selecting an agent

```bash
make reasoning-run AGENT=assistant         # full external API access
make reasoning-run AGENT=local_assistant   # local-only (default)
```

---

## Execution Log

Every query produces two artefacts:

| File | Content |
|------|---------|
| `log/{execution_id}.json` | Full execution record: query, tool inputs/outputs, synthesis, metrics |
| `log/summary.jsonl` | Append-only index of all executions |

Always use structured logging via `logging_handler.py`. Do not use `print()` for observability in Python modules.
