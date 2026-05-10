# System Architecture

## Overview

Clinical Agents is built on a configuration-first, separation-of-concerns architecture. All agent behavior, tool configuration, and model selection are expressed in YAML files. Python code provides the execution engine; YAML provides the policy. This inversion keeps the codebase stable while allowing rapid iteration on agent behavior.

## Architectural Principles

**Configuration-First Design.** Every behavioral change — swapping models, enabling tools, adjusting temperature — is made in YAML, not Python. This allows non-engineers to modify agent behavior without touching source code.

**Separation of Concerns.** Each module has exactly one responsibility. Config loading, agent execution, tool invocation, workflow orchestration, logging, and the CLI are fully decoupled and communicate through defined interfaces.

**Loose Coupling via Interfaces.** Components depend on abstractions, not concrete implementations. The agent depends on BaseTool, not OpenFDATool. The CLI depends on SimpleAgent, not ChatOllama.

**Lazy Loading.** Tools are loaded only when a tools directory exists and is non-empty. This reduces startup overhead and keeps failure domains isolated.

**Flexible Execution Modes.** The system provides a synchronous ReAct agent via LangGraph for interactive and latency-sensitive use, plus a parallel fan-out path via `run_parallel()` when deterministic concurrent tool execution is preferred.

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
    |                +-- run_parallel() fan-out (concurrent tool mode)
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

## Query Execution: Parallel Tool Mode

When concurrent fan-out is selected, the CLI calls `SimpleAgent.run_parallel()`. This wraps each `tool.cached_execute(query)` call in `asyncio.to_thread`, awaits all tasks with `asyncio.gather`, and then passes the aggregated tool results to the synthesis step. This mode keeps orchestration inside the application process while still parallelising external tool calls.

## Logging Phase

After every execution (direct, ReAct, or parallel), the CLI calls `_log_execution()`, which extracts metrics from the agent and calls `ExecutionLogger.log_execution()`. The logger writes a complete JSON object to `log/{execution_id}.json` and appends the same object as a single line to `log/summary.jsonl`. The current Git commit hash is captured and included in the log entry.

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

## Data Flow: Parallel Tool Example

A user runs: `python -m src.cli --parallel "Side effects of semaglutide?"`

1. CLI loads config and constructs `SimpleAgent` with the configured tools.
2. `run_parallel()` selects the requested tools and wraps each `tool.cached_execute()` call in `asyncio.to_thread`.
3. `asyncio.gather` schedules the tool calls concurrently.
4. Results are gathered into a single tool-result map.
5. The synthesis step calls the LLM with all aggregated context.
6. CLI displays the synthesis and logs execution with `router_intent: "parallel"`.

## Design Patterns

**Registry.** `ToolRegistry` centralises tool discovery and instantiation, decoupling agents from implementation classes.

**Template Method.** `BaseTool` defines the interface contract; subclasses fill in `execute()`. The framework handles registration and invocation.

**Decorator/Wrapper.** LangChain's `@lc_tool` wraps tool instances for ReAct agent compatibility without modifying tool classes.

**Composition.** `SimpleAgent` composes `ChatOllama`, an optional `ToolRegistry`, and an optional ReAct agent rather than inheriting from any of them.

**Command.** `run_parallel()` encapsulates fan-out and synthesis as a repeatable execution path for deterministic multi-tool queries.

## Fault Tolerance

**Tool loading failures.** Invalid YAML or missing implementation classes are caught per-tool. The registry continues with all remaining tools.

**Tool invocation failures.** In ReAct mode, tool errors are returned as strings and included in the LLM context. In parallel mode, failed tool calls are captured as error strings and passed to the synthesis step alongside successful results.

**LLM unavailability.** `SimpleAgent.run()` does not catch LLM errors; they propagate to the CLI and are displayed to the user. The `finally` block ensures `metrics.end_time` is always recorded.

## Data Directories

The project stores runtime data under `data/`, committed to `.gitignore` and owned by the application.

| Path | Contents |
|---|---|
| `data/models/` | Cached HuggingFace embedding models. Populated by `make download-models` or on first `GraphRAGTool` invocation. The `BAAI/bge-small-en-v1.5` model is stored here as `models--BAAI--bge-small-en-v1.5/`. |

This directory is not committed to source control. Delete it to reset local model state; re-run `make download-models` to restore.

## Extensibility Points

**New tools.** Implement `BaseTool`, create a YAML config, reference by name in an agent config. No code outside `src/tools/implementations/` needs to change. For tools with heavy dependencies (ML models, database clients), use lazy initialisation so registration is instantaneous.

**New agents.** Create a YAML file in `config/agentic-reasoning/agents/`. No code changes needed.

**New execution strategies.** Add new orchestration paths in `src/agent.py` or the CLI when a new concurrency or routing strategy is needed.

**New configuration schemas.** Add Pydantic models in `src/schemas/` with a corresponding loader function.

## Future Evolution Targets

The architecture is designed to absorb these additions without restructuring:

FastAPI server layer for multi-user REST API access.
OPA policy engine for HIPAA-compliant access control and consent management.
Async tool implementations to replace `asyncio.to_thread` wrapping.
