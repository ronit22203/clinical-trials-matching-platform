# Temporal Workflow System

## Overview

The Temporal integration adds a durable, retryable execution path alongside the synchronous ReAct agent. Where the ReAct agent is fast and stateless, the Temporal path is resilient: it survives worker restarts, retries failed activities automatically, runs tools in parallel, and produces a full event history in the Temporal Web UI. It is the appropriate choice for production workloads and any scenario where an audit trail of each execution step is required.

The Temporal path also implements a human-in-the-loop (HITL) approval gate. When enabled, the workflow pauses after tool results are collected and waits for an explicit operator signal before invoking the LLM for synthesis. This allows a human reviewer to inspect raw tool data and decide whether synthesis should proceed.

## Source Locations

| Component | Path |
|---|---|
| Activity definitions | `src/temporal/activities.py` |
| Workflow definition | `src/temporal/workflows.py` |
| Worker process | `src/temporal/worker.py` |
| Client helpers | `src/temporal/client.py` |
| Docker Compose | `docker-compose.yml` |

## Temporal Concepts

**Workflow.** A durable, deterministic function that orchestrates activities. Workflows must not perform I/O, make random decisions, or use wall-clock time directly. All side effects must happen inside activities.

**Activity.** An isolated, retryable unit of work. Activities can do I/O, call APIs, invoke LLMs, and block threads. Each activity is executed by a worker and retried independently on failure.

**Signal.** An external message sent to a running workflow that changes its internal state. The `approve` signal advances the workflow past the HITL gate.

**Query.** A read-only inspection of a running workflow's state. The `get_tool_results` query returns collected tool results before synthesis completes.

**Worker.** A process that polls the Temporal server for tasks, executes activities and workflows, and returns results.

**Task Queue.** A named channel on the Temporal server that routes work to specific workers. All components in this codebase use `"clinical-research-queue"`.

**Temporal Server.** The central orchestration service that persists workflow state, schedules activities, and manages retries. Runs on `localhost:7233` in the local Docker Compose setup.

## Infrastructure Setup

The `docker-compose.yml` defines three services:

**postgres.** PostgreSQL 13 used as Temporal's persistence backend. Exposes port `5432`. Data is persisted to `./data/postgres`. A health check ensures Temporal waits for the database to be ready before starting.

**temporal.** The `temporalio/auto-setup` image handles schema creation automatically. Exposes gRPC port `7233` for SDK connections. Configured to use the `postgres` service as its database.

**temporal-ui.** The `temporalio/ui` web interface. Exposes port `8080`. Connect to `http://localhost:8080` to view workflow history, inspect activity results, and debug failures.

Start all three services:

```bash
make temporal-up
```

Stop all services:

```bash
make temporal-down
```

## Activities

Activities are defined in `src/temporal/activities.py` and decorated with `@activity.defn`.

### distill_query_activity

```python
async def distill_query_activity(query: str, model: str) -> str
```

**Purpose.** Extract the single most specific clinical concept (drug name, condition, intervention, or biomarker) from a free-form user query. Returns a concise search term suitable for clinical APIs that do not perform their own natural-language query refinement.

**Process.** Calls the configured LLM at `temperature=0.0` with a focused system prompt instructing it to return only the search term — no explanation or punctuation. The LLM call runs in `asyncio.to_thread`. If the model returns an empty string or a response longer than 120 characters, the raw `query` is returned as a fallback.

**When it runs.** This is the first activity executed in `ClinicalResearchWorkflow`, before the parallel tool fan-out. All tool activities receive the distilled term rather than the raw user query.

**Why separate from tool activities.** Distillation is done once per workflow run (not once per tool) to avoid N redundant LLM calls. Placing it as a sequential pre-step is intentional: the small latency cost (typically &lt;2 seconds) is outweighed by the quality improvement across all tool results.

**Retry policy.** Uses the shared `RETRY_POLICY` with a 30-second timeout.

### execute_tool_activity

```python
async def execute_tool_activity(tool_name: str, query: str) -> str
```

**Purpose.** Load a single tool from the registry and execute it against the distilled query.

**Process.** Creates a fresh `ToolRegistry` from `config/agentic-reasoning/tools/`, retrieves the tool by name, and calls `tool.execute(query)` wrapped in `asyncio.to_thread`. The result is converted to a string for Temporal serialisation.

**Input.** In Temporal mode, `query` is the distilled clinical term produced by `distill_query_activity` (not the raw user query). Individual tool implementations may apply additional input sanitisation (e.g., `_extract_drug_name()` in `OpenFDATool` and `ClinicalTrialsTool`).

**Error behaviour.** If the tool is not found, raises `ValueError`. If `tool.execute()` raises, the exception triggers the Temporal retry policy. If the tool returns an error string (the tool system convention), that string is passed through to synthesis.

**Why asyncio.to_thread.** All built-in tool implementations are synchronous (they use `requests.Session`). Wrapping them in `asyncio.to_thread` prevents the activity worker's event loop from blocking.

### synthesize_results_activity

```python
async def synthesize_results_activity(
    query: str,
    tool_results: dict[str, str],
    model: str,
    system_prompt: str,
) -> str
```

**Purpose.** Call the LLM to synthesise all tool results into a comprehensive answer.

**Process.** Extracts the model name from the `provider/model-name` format, creates a `ChatOllama` instance, separates GraphRAG results from external API results, and invokes the LLM with a structured synthesis prompt. The LLM call is wrapped in `asyncio.to_thread`.

**GraphRAG elevation.** Results from tools whose name contains `"graphrag"` are listed first under a dedicated section header (`=== INTERNAL KNOWLEDGE BASE (treat as primary evidence) ===`) and the synthesis prompt explicitly instructs the LLM to cite them directly and not dismiss them. External database results appear under `=== EXTERNAL CLINICAL DATABASES ===`. This prevents the LLM from treating curated internal knowledge as a fallback.

**Input format.** `tool_results` is a dict mapping tool names to their string results (or error strings). The formatted prompt seen by the LLM:

```
Query: <original user query>

=== INTERNAL KNOWLEDGE BASE (treat as primary evidence) ===
[graphrag_search]
{"query": ..., "vector_results": [...], "graph_facts": [...]}

=== EXTERNAL CLINICAL DATABASES ===
[fda_adverse_events]
{"total_reports": 6027, "results": [...]}

[pubmed_search]
[{"pmid": "38123456", "title": "...", ...}]

Instructions:
- Internal knowledge base results are primary evidence...
```

## Workflow

Defined in `src/temporal/workflows.py`. The class is decorated with `@workflow.defn`.

### ClinicalResearchWorkflow

```python
@workflow.defn
class ClinicalResearchWorkflow:
    async def run(
        self,
        query: str,
        tools: list[str],
        model: str,
        system_prompt: str,
        require_approval: bool = False,
    ) -> dict
```

**State.** The workflow instance holds two mutable fields:

| Field | Type | Purpose |
|---|---|---|
| `_approved` | bool | Set to `True` when the `approve` signal is received. |
| `_tool_results` | dict[str, str] | Populated with tool results after parallel execution. |

**Signal: approve**

```python
@workflow.signal
async def approve(self) -> None
```

An external signal sent by an operator to advance the workflow past the HITL gate. Setting `_approved = True` satisfies the `wait_condition` predicate.

**Query: get_tool_results**

```python
@workflow.query
def get_tool_results(self) -> dict[str, str]
```

A read-only query that returns the current value of `_tool_results`. This is called by the client while the workflow is paused at the approval gate, allowing the CLI to display tool results to the operator before they decide to approve.

**Determinism requirement.** Temporal replays workflow history to reconstruct state after failures. Any non-deterministic code in a workflow (random numbers, wall-clock time, direct I/O) will cause replay divergence. All I/O is delegated to activities.

**Parallel tool execution.** All tool activities are scheduled simultaneously using a list comprehension of `workflow.execute_activity()` calls against the distilled query, then awaited together with `asyncio.gather(..., return_exceptions=True)`. Total wall-clock time is approximately that of the slowest tool.

**Fault isolation.** `return_exceptions=True` in `asyncio.gather` prevents a single tool failure from cancelling other tool tasks. Exceptions are captured as error strings and stored in `_tool_results`.

**Retry policy.** Both tool and synthesis activities use a shared `RetryPolicy`:

| Parameter | Value |
|---|---|
| maximum_attempts | 3 |
| initial_interval | 1 second |
| maximum_interval | 10 seconds |
| backoff_coefficient | 2.0 |

**Timeouts.**

| Activity | Timeout |
|---|---|
| distill_query_activity | 30 seconds |
| execute_tool_activity | 30 seconds |
| synthesize_results_activity | 120 seconds |
| HITL approval gate | 10 minutes |

**HITL gate behaviour.** When `require_approval=True`, after `_tool_results` is populated the workflow calls:

```python
await workflow.wait_condition(lambda: self._approved, timeout=APPROVAL_TIMEOUT)
```

If `approve()` is signalled before the timeout, synthesis proceeds normally. If the timeout expires, the workflow returns immediately with `synthesis` set to `"Workflow timed out waiting for human approval."` and `approved: False`.

**Return value.**

```python
{
    "query": str,
    "tool_results": {"tool_name": "result string", ...},
    "synthesis": str,
    "approved": bool | None,   # None when require_approval=False
    "workflow_id": str,
    "run_id": str,
}
```

### Import Isolation

Activity imports inside the workflow file are wrapped in `workflow.unsafe.imports_passed_through()`:

```python
with workflow.unsafe.imports_passed_through():
    from src.temporal.activities import execute_tool_activity, synthesize_results_activity, distill_query_activity
```

This tells the Temporal SDK that these imports should not be sandboxed. Without this, the SDK's import restrictions would raise an error at workflow registration time.

## Worker

`src/temporal/worker.py` is the long-running process that executes activities and workflows.

```bash
make temporal-worker
```

The worker calls `load_dotenv()` at module startup — before any activity code is imported — so environment variables from `.env` (including `OPENFDA_API_KEY` and `OLLAMA_BASE_URL`) are available inside every activity invocation. This is critical for the Temporal path because the worker is a separate process that does not inherit environment variables loaded by the CLI.

The worker connects to `localhost:7233`, registers `ClinicalResearchWorkflow` and all three activities (`distill_query_activity`, `execute_tool_activity`, `synthesize_results_activity`) against the `"clinical-research-queue"` task queue, and enters a polling loop. The worker must be running before any `--use-temporal` CLI invocation can succeed.

Multiple worker processes can be started against the same task queue for horizontal scaling. Temporal distributes tasks across available workers.

## Client

`src/temporal/client.py` provides the functions consumed by the CLI.

### run_research_workflow (async)

Connects to the Temporal server, calls `client.execute_workflow()` with a timestamp-based workflow ID, and awaits the result. Blocks until the workflow completes.

### run_research_sync

Synchronous wrapper using `asyncio.run()`. Called by the CLI for standard (non-HITL) Temporal queries.

### start_research_workflow (async)

Starts a workflow without waiting for completion. Returns `(handle, workflow_id)`. Used by the HITL flow to begin execution while the client polls for tool results.

### poll_tool_results (async)

Queries a running workflow for its current `_tool_results`. Returns `None` if results are not yet available (the parallel tool activities have not all completed). The client polls this every second for up to 60 seconds.

### send_approval (async)

Sends the `approve` signal to a workflow identified by `workflow_id`. Used by the CLI after the operator confirms they want synthesis to proceed.

### run_hitl_sync

Synchronous end-to-end HITL flow:

```
1. Start workflow with require_approval=True via start_research_workflow.
2. Poll poll_tool_results every second until results are populated (up to 60s).
3. Call display_fn(workflow_id, tool_results) to show results to the operator.
4. Call prompt_fn() -> bool to capture operator decision.
5. If approved, call send_approval(workflow_id).
6. Await handle.result() and return the workflow result dict.
```

The `display_fn` and `prompt_fn` are provided by the CLI, keeping I/O out of the client module.

## CLI Integration

### Standard Temporal Mode

```bash
# Interactive
make run-temporal

# One-off query
make temporal-run QUERY="Side effects of semaglutide?"
```

The CLI calls `run_research_sync()`. Tool names are extracted from the agent config's `tools` list. The model and system prompt are forwarded from the same YAML that controls direct ReAct execution.

### Human-in-Loop Mode

```bash
# Interactive
make run-temporal-hitl

# One-off query
make temporal-run-hitl QUERY="Side effects of semaglutide?"
```

The CLI calls `run_hitl_sync()` with two callbacks:

**display_fn.** Prints each tool name as a Rich rule header and the first 800 characters of its result.

**prompt_fn.** Calls `console.input("Approve synthesis? (y/n):")` and returns `True` for `y` or `yes`.

Both interactive and one-off modes are supported. In interactive mode, a new workflow is started per query.

## Full Startup Sequence

```bash
# Terminal 1: start Temporal infrastructure
make temporal-up

# Terminal 2: start the activity/workflow worker
make temporal-worker

# Terminal 3: run interactive session (auto-synthesise)
make run-temporal

# Terminal 3 (alternative): run interactive session with HITL
make run-temporal-hitl

# Inspect workflow execution history
open http://localhost:8080
```

## Query Distillation and Tool Input Sanitisation

### LLM-Based Distillation (Temporal path)

In Temporal mode the raw user query (e.g., "What are the cardiovascular risk factors associated with metformin treatment in type 2 diabetes?") is never passed directly to tool APIs. `distill_query_activity` is called once at the start of each workflow run and extracts the core clinical concept using the LLM. All tool activities then receive this focused term (e.g., `"metformin cardiovascular risk"`) rather than the full sentence.

This is necessary because Temporal workflows fan out to all tools simultaneously — unlike the ReAct agent, where the LLM decides what input to pass to each tool individually. Without distillation, tools that require clean identifiers (openFDA, ClinicalTrials.gov) receive sentences, which causes 400 errors or irrelevant results.

### Regex-Based Sanitisation (individual tools)

Even with a distilled query, individual tools apply their own input sanitisation as a second layer:

`_extract_drug_name()` in `src/tools/implementations/openfda.py` uses regular expressions to strip any remaining clinical question prefixes (e.g., "side effects of", "adverse events for") before the drug name is used as the `medicinalproduct` search filter. Both `OpenFDATool` and `ClinicalTrialsTool` call this function.

PubMed accepts natural-language queries natively via the NCBI eUtils API and does not require sanitisation.

| Layer | Where | Mechanism |
|---|---|---|
| LLM distillation | `distill_query_activity` | LLM extraction, once per workflow |
| Regex sanitisation | `OpenFDATool`, `ClinicalTrialsTool` | `_extract_drug_name()` on each tool call |

### API Key Injection

`OpenFDATool.execute()` reads the FDA API key with the following precedence:

1. `config["api_key"]` from the tool's YAML config block.
2. `os.getenv("OPENFDA_API_KEY")` as a fallback.

The worker's `load_dotenv()` call at startup ensures `.env` is loaded before any tool executes, so the env var fallback works correctly in the Temporal worker process even though the `.env` is not explicitly referenced in the tool YAML.

## Workflow ID Convention

Workflow IDs are generated as `research-{unix_timestamp}`. They are visible in the Temporal Web UI and included in the CLI output below the synthesis. The `run_id` (generated by Temporal) uniquely identifies a specific execution attempt and is also included in the log entry.

## Known Constraints

**Synchronous tools.** All built-in tools use `requests` synchronously. The `asyncio.to_thread` wrapper is the current solution. Future tool implementations should use `httpx` with native async support.

**No working directory dependency.** `execute_tool_activity` creates `ToolRegistry(REPO_ROOT / "config" / "agentic-reasoning" / "tools")`, so the worker resolves tool configs from the repo-root config tree instead of relying on the current shell directory.

**Single LLM instance per activity.** `synthesize_results_activity` creates a new `ChatOllama` instance per invocation. Connection reuse is not implemented.

**Poll timeout.** `run_hitl_sync` polls for tool results for up to 60 seconds. If all tools take longer than 60 seconds, the CLI will display empty tool results and still prompt for approval.

## Future Extensions

**Async tool implementations.** Rewriting tools to use `httpx` would eliminate `asyncio.to_thread` and allow true async parallelism within a single activity.

**Child workflows.** Complex research tasks could be decomposed into child workflows, each handling a distinct research phase with its own retry policy and timeout.

**Workflow versioning.** As the workflow definition evolves, `workflow.patched()` allows backward-compatible changes that do not break in-flight workflow replays.

**Signal timeout notification.** The HITL timeout currently returns a static string. A future version could emit a Temporal signal or webhook to notify an external system that approval was not received.
