# API Reference

## Base URL

```
http://localhost:8000
```

The server is started with `make serve-api` (or `make serve`). It runs under `uvicorn` with hot reload enabled in development.

CORS is configured to accept requests from `http://localhost:3000` and `http://127.0.0.1:3000`.

---

## Endpoints

### `POST /api/query`

Submit a natural language query to the agent. The agent selects tools, executes them (concurrently), and returns a synthesised response with full execution metadata.

#### Request

```
Content-Type: application/json
```

```json
{
  "query": "string",
  "tools": ["string"],
  "mode": "langgraph",
  "agent_config": "string"
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `query` | `string` | Yes | — | Natural language query. 1–4096 characters. |
| `tools` | `string[]` | No | Agent config defaults | Override the tool list for this request. An empty array uses the agent's configured defaults. |
| `mode` | `"langgraph"` | No | `"langgraph"` | Execution runtime. LangGraph ReAct orchestrates tool use and synthesis. |
| `agent_config` | `string` | No | `"local_assistant"` | Named agent configuration key from `config/app.yaml`. |

#### Response `200 OK`

```json
{
  "synthesis": "string",
  "executionLog": {
    "executionId": "string (UUID)",
    "model": "string",
    "latencyMs": 0.0,
    "toolsCalled": ["string"],
    "tokensInput": 0,
    "tokensOutput": 0,
    "gitCommit": "string",
    "routerIntent": "langgraph",
    "entries": [
      {
        "id": "string",
        "step": "query_submitted | tool_called | data_retrieved | final_decision",
        "label": "string",
        "timestamp": "ISO 8601",
        "durationMs": 0,
        "toolName": "string | null",
        "rawJson": {}
      }
    ]
  },
  "toolResults": {
    "<tool_name>": "string"
  }
}
```

All response fields are **camelCase** (Pydantic serialises from Python snake_case via `alias_generator`).

| Field | Description |
|-------|-------------|
| `synthesis` | Final agent response text. Qwen3 chain-of-thought tags (`<think>...</think>`) are stripped before returning. |
| `executionLog.executionId` | UUID identifying this execution. Used to locate the corresponding log file at `log/{executionId}.json`. |
| `executionLog.latencyMs` | Wall-clock time from request receipt to response completion, in milliseconds. |
| `executionLog.toolsCalled` | Names of tools that returned a non-empty result. |
| `executionLog.entries` | Ordered audit trail of pipeline steps. |
| `toolResults` | Raw text output from each tool, keyed by tool name. |

#### Response `422 Unprocessable Entity`

Returned when request validation fails (e.g. `query` is empty or exceeds 4096 characters).

```json
{
  "detail": [
    {
      "loc": ["body", "query"],
      "msg": "String should have at least 1 character",
      "type": "string_too_short"
    }
  ]
}
```

#### Response `500 Internal Server Error`

```json
{
  "detail": "Agent error: <description>"
}
```

Indicates an unhandled exception during agent execution. Check `agentic-reasoning/log/` for the full stack trace.

---

### `GET /api/health`

Liveness probe. Returns immediately without executing any agent logic.

#### Response `200 OK`

```json
{
  "status": "ok",
  "version": "0.1.0"
}
```

---

## TypeScript Client

A typed client is provided at `platform-ui/src/lib/api/client.ts`:

```typescript
import { queryAgent, getHealth } from "@/lib/api/client";

// Submit a query
const result = await queryAgent({
  query: "What biomarkers predict sepsis mortality?",
  mode: "langgraph",
  tools: ["graphrag"],
});

console.log(result.synthesis);
console.log(result.executionLog.executionId);
console.log(result.toolResults.graphrag);

// Health check
const health = await getHealth();
console.log(health.status); // "ok"
```

The base URL is read from the `NEXT_PUBLIC_API_URL` environment variable (defaults to `http://localhost:8000`).

---

## curl Examples

```bash
# Basic query (LangGraph, default tools)
curl -s -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What is AUROC?"}' | jq .synthesis

# Query with specific tools
curl -s -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "List sepsis biomarkers from the ingested documents",
    "mode": "langgraph",
    "tools": ["graphrag"]
  }' | jq '{id: .executionLog.executionId, tools: .executionLog.toolsCalled}'

# Health check
curl -s http://localhost:8000/api/health | jq .
```

---

## Interactive API Documentation

Swagger UI is available at `http://localhost:8000/docs` when the server is running.
ReDoc is available at `http://localhost:8000/redoc`.

---

## Execution Log Files

In addition to the API response, every query writes two files:

| Path | Format | Content |
|------|--------|---------|
| `agentic-reasoning/log/{executionId}.json` | JSON | Full execution record: query, tool inputs and outputs, synthesis, all metrics |
| `agentic-reasoning/log/summary.jsonl` | JSONL (append-only) | One line per execution: ID, timestamp, model, latency, tool count |

These files are not served by the API. To download the execution log for the current session, use the "Download" button on the Execution Logs card in the UI — this triggers a client-side download of the `executionLog` object from the last query response.
