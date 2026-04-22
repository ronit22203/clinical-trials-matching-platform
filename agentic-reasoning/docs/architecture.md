# System Architecture

## Overview

Clinical Agents is built on a configuration-first, separation-of-concerns architecture. All agent behavior, tool configuration, and model selection are expressed in YAML files. Python code provides the execution engine; YAML provides the policy. This inversion keeps the codebase stable while allowing rapid iteration on agent behavior.

## Architectural Principles

**Configuration-First Design.** Every behavioral change — swapping models, enabling tools, adjusting temperature — is made in YAML, not Python. This allows non-engineers to modify agent behavior without touching source code.

**Separation of Concerns.** Each module has exactly one responsibility. Config loading, agent execution, tool invocation, workflow orchestration, logging, and the CLI are fully decoupled and communicate through defined interfaces.

**Loose Coupling via Interfaces.** Components depend on abstractions, not concrete implementations. The agent depends on BaseTool, not OpenFDATool. The CLI depends on SimpleAgent, not ChatOllama.

**Lazy Loading.** Tools are loaded only when a tools directory exists and is non-empty. The Temporal workflow path is only initialised when --use-temporal is passed. This reduces startup overhead and keeps failure domains isolated.

**Dual Execution Modes.** The system provides two runtime paths: a synchronous ReAct agent via LangGraph for interactive and latency-sensitive use, and a durable Temporal workflow for long-running, retryable, parallel execution.

## Component Map

```
User Input
    |
    v
CLI (src/cli.py)
    |
    +-- load --> ConfigLoader (src/config_loader.py)
    |                |
    |                v
    |            AgentConfig (YAML in config/agentic-reasoning/agents/)
    |
    +-- load --> ToolRegistry (src/tools/registry.py)
    |                |
    |                v
    |            Tool Instances (config/agentic-reasoning/tools/ + src/tools/implementations/)
    |
    +-- create --> SimpleAgent (src/agent.py)
    |                |
    |                +-- LangChain ChatOllama (direct mode)
    |                +-- LangGraph ReAct Agent (tool mode)
    |
    +-- OR --> Temporal Client (src/temporal/client.py)
    |                |
    |                v
    |            ClinicalResearchWorkflow (src/temporal/workflows.py)
    |                |
    |                +-- execute_tool_activity (parallel, retried)
    |                +-- synthesize_results_activity
    |
    +-- log --> ExecutionLogger (src/logging_handler.py)
                     |
                     v
                 log/{id}.json + log/summary.jsonl
```

## Configuration Loading Phase

The CLI receives file path arguments for the agent config and tools directory. It calls `load_agent_config(path)`, which opens the YAML file, deserialises it with `yaml.safe_load`, and validates the result against the `AgentConfig` Pydantic model. Validation failure raises a `ValidationError` with field-level diagnostics.

The `ToolRegistry` is initialised separately. It scans the tools directory for all `.yaml` files, validates each against the `ToolConfig` schema, dynamically imports the specified module and class, and instantiates each tool with its config dictionary. Failed tools are skipped with a logged error; the registry continues loading remaining tools.

## Agent Initialisation Phase

`SimpleAgent` is constructed with the validated `AgentConfig` and the optional `ToolRegistry`. If both are present and `config.tools` is non-empty, `_build_langchain_tools()` wraps each tool instance in a LangChain `@lc_tool` decorator and passes the resulting list to `create_react_agent()`. The ReAct agent is stored as `self._agent`. If either condition is missing, `self._agent` remains `None` and the agent operates in direct LLM mode.

## Query Execution: Direct Mode

When `self._agent` is `None`, `SimpleAgent.run()` constructs a message list containing an optional `SystemMessage` (from `config.system_prompt`) followed by a `HumanMessage` (from the user query) and calls `ChatOllama.invoke()`. The response content is extracted and returned.

## Query Execution: ReAct Tool Mode

When `self._agent` is set, `run()` passes a single `HumanMessage` to the ReAct agent. The agent uses the LLM to decide which tools to call, invokes them via the wrapped `@lc_tool` functions, feeds results back to the LLM, and iterates until a final answer is produced. Each tool invocation appends the tool name to `metrics.tools_called`.

## Query Execution: Temporal Workflow Mode

When `--use-temporal` is passed, the CLI skips `SimpleAgent` entirely and calls `run_research_sync()` from `src/temporal/client.py`. This connects to a Temporal server, starts a `ClinicalResearchWorkflow`, and blocks until the result is returned. The workflow runs all configured tool activities in parallel using `asyncio.gather`, then passes aggregated results to the synthesis activity. Each activity has an independent retry policy and timeout. The worker process (`src/temporal/worker.py`) must be running separately.

## Logging Phase

After every execution (both direct and Temporal), the CLI calls `_log_execution()`, which extracts metrics from the agent and calls `ExecutionLogger.log_execution()`. The logger writes a complete JSON object to `log/{execution_id}.json` and appends the same object as a single line to `log/summary.jsonl`. The current Git commit hash is captured and included in the log entry.

## Data Flow: Direct Query Example

A user runs: `python -m src.cli "What is HbA1c?"`

1. CLI loads `config/agentic-reasoning/agents/assistant.yaml` into `AgentConfig`.
2. `ToolRegistry` loads three tools from `config/agentic-reasoning/tools/`.
3. `SimpleAgent` builds a ReAct agent with the three tools.
4. `run("What is HbA1c?")` invokes the ReAct agent.
5. The LLM determines no tool is needed and responds directly.
6. CLI displays the response. Logger writes `log/{id}.json`.

## Data Flow: Tool-Augmented Query Example

A user runs: `python -m src.cli "Side effects of metformin?"`

1. CLI loads config and creates `SimpleAgent` with tools.
2. `run()` invokes the ReAct agent.
3. The LLM decides to call `fda_adverse_events` and `pubmed_search`.
4. Both tools execute and return structured data.
5. The LLM synthesises a final answer from the tool results.
6. CLI displays the response. Logger writes log entry with `tools_called: ["fda_adverse_events", "pubmed_search"]`.

## Data Flow: Temporal Workflow Example

A user runs: `python -m src.cli --use-temporal "Side effects of semaglutide?"`

1. CLI loads config, extracts tool names and model.
2. Calls `run_research_sync()` which connects to Temporal on `localhost:7233`.
3. `ClinicalResearchWorkflow.run()` schedules three tool activities in parallel.
4. Each activity loads a fresh `ToolRegistry` and calls `tool.execute()` in a thread.
5. Results are gathered; `synthesize_results_activity` calls the LLM with all context.
6. Workflow returns structured result to the CLI.
7. CLI displays the synthesis and logs execution with `router_intent: "temporal"`.

## Design Patterns

**Registry.** `ToolRegistry` centralises tool discovery and instantiation, decoupling agents from implementation classes.

**Template Method.** `BaseTool` defines the interface contract; subclasses fill in `execute()`. The framework handles registration and invocation.

**Decorator/Wrapper.** LangChain's `@lc_tool` wraps tool instances for ReAct agent compatibility without modifying tool classes.

**Composition.** `SimpleAgent` composes `ChatOllama`, an optional `ToolRegistry`, and an optional ReAct agent rather than inheriting from any of them.

**Command.** The Temporal workflow encapsulates an entire research operation as a durable, serialisable unit of work.

## Fault Tolerance

**Tool loading failures.** Invalid YAML or missing implementation classes are caught per-tool. The registry continues with all remaining tools.

**Tool invocation failures.** In ReAct mode, tool errors are returned as strings and included in the LLM context. In Temporal mode, failed activities are retried up to three times with exponential backoff; persistent failures are captured as error strings and passed to the synthesis step.

**Temporal worker unavailability.** The CLI catches the connection error, displays an actionable message (run `make temporal-worker`), and exits cleanly.

**LLM unavailability.** `SimpleAgent.run()` does not catch LLM errors; they propagate to the CLI and are displayed to the user. The `finally` block ensures `metrics.end_time` is always recorded.

## Data Directories

The project has two distinct data directories with different purposes:

**`data/`** — project runtime data, committed to `.gitignore`, owned by the application.

| Path | Contents |
|---|---|
| `data/models/` | Cached HuggingFace embedding models. Populated by `make download-models` or on first `GraphRAGTool` invocation. The `BAAI/bge-small-en-v1.5` model is stored here as `models--BAAI--bge-small-en-v1.5/`. |
| `data/postgres/` | PostgreSQL data volume for Temporal's backing database. Mapped by `infra/docker-compose.yml` (`./data/postgres`). |

**`infra/data/`** — Docker volume mounts for infrastructure services defined in `infra/docker-compose.graphrag.yml`.

| Path | Contents |
|---|---|
| `infra/data/postgres/` | PostgreSQL data volume for the Temporal service (same volume as `data/postgres/`, resolved relative to the compose file location). |

Neither directory is committed to source control. Delete them to reset infrastructure state; re-run `make services-up` and `make download-models` to restore.

## Extensibility Points

**New tools.** Implement `BaseTool`, create a YAML config, reference by name in an agent config. No code outside `src/tools/implementations/` needs to change. For tools with heavy dependencies (ML models, database clients), use lazy initialisation so registration is instantaneous.

**New agents.** Create a YAML file in `config/agentic-reasoning/agents/`. No code changes needed.

**New workflow types.** Add new `@workflow.defn` classes in `src/temporal/` and register them in the worker.

**New configuration schemas.** Add Pydantic models in `src/schemas/` with a corresponding loader function.

## Future Evolution Targets

The architecture is designed to absorb these additions without restructuring:

FastAPI server layer for multi-user REST API access.
OPA policy engine for HIPAA-compliant access control and consent management.
Async tool implementations to replace `asyncio.to_thread` wrapping.
