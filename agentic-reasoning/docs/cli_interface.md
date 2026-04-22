# CLI Interface

## Overview

The command-line interface is the primary entry point for interacting with the Clinical Agents platform. Built with Click and Rich, it ties together configuration loading, agent execution, tool registry initialisation, workflow routing, and structured logging into a single command. The CLI supports one-off query execution, an interactive conversation loop, and durable Temporal workflow execution.

## Source Location

`src/cli.py`

## Entry Points

The canonical invocation is:

```bash
python -m src.cli [OPTIONS] [QUERY]
```

The `clinical-agents` script entry point (defined in `pyproject.toml`) has known module resolution issues and should not be relied on until fixed.

The `make run` target calls `.venv/bin/python -m src.cli --agent config/agentic-reasoning/agents/assistant.yaml`.

## Options and Arguments

| Flag | Default | Description |
|---|---|---|
| `--agent`, `-a` | `config/agentic-reasoning/agents/assistant.yaml` | Path to the agent YAML configuration file. |
| `--tools-dir` | `config/agentic-reasoning/tools` | Directory containing tool YAML files. |
| `--log-dir` | `log` | Directory for JSON execution logs. |
| `--use-temporal` | False (flag) | Route queries through a Temporal workflow instead of SimpleAgent. Supports both one-off and interactive modes. |
| `--human-in-loop` | False (flag) | When combined with `--use-temporal`, pauses the workflow after tool results are collected and waits for explicit operator approval before synthesis. |
| `--parallel` | False (flag) | Fan out all configured tool calls concurrently before LLM synthesis, bypassing the ReAct loop. Uses `SimpleAgent.run_parallel()`. Cannot be combined with `--use-temporal`. |
| `QUERY` | (optional) | The user query. Omitting it enters interactive mode. |

## Execution Modes

### One-Off Query

When `QUERY` is provided and `--use-temporal` is not set:

```bash
python -m src.cli "What are the clinical indications for metformin?"
```

The agent streams the response token-by-token to the terminal, logs the execution, and exits. Pass `--parallel` to fan out tool calls concurrently before synthesis instead of using the ReAct loop:

```bash
python -m src.cli --parallel "What are the clinical indications for metformin?"
```

### Interactive Mode

When no `QUERY` is provided and `--use-temporal` is not set, the CLI enters a loop:

```bash
python -m src.cli
```

The prompt `You:` is displayed in bold cyan using the Rich console. Responses are streamed token-by-token; the agent prints each token as it is generated rather than buffering the full completion. Typing `exit` or `quit` (case-insensitive) terminates the loop.

Interactive mode maintains a single `SimpleAgent` instance across turns, so the Ollama model remains loaded between queries. It does not maintain conversation history between turns; each query is independent.

Pass `--parallel` to use concurrent tool pre-fetch for every query in the session:

```bash
python -m src.cli --parallel
```

In parallel mode the CLI displays a spinner while tool calls run concurrently, then renders the synthesised response as Markdown.

### Temporal Workflow Mode

When `--use-temporal` is passed, the CLI bypasses `SimpleAgent` entirely and routes each query through a `ClinicalResearchWorkflow`. Both one-off and interactive modes are supported.

**One-off query:**

```bash
python -m src.cli --use-temporal "Side effects of semaglutide?"
```

**Interactive mode (Temporal, auto-synthesise):**

```bash
python -m src.cli --use-temporal
```

Entering interactive mode with `--use-temporal` starts a new Temporal workflow per query. The prompt behaves identically to the standard interactive loop. Typing `exit` or `quit` terminates the session.

**Interactive mode with human-in-loop review:**

```bash
python -m src.cli --use-temporal --human-in-loop
```

After tool results are collected, the CLI displays each tool's raw result in the terminal. The operator is then prompted:

```
Approve synthesis? (y/n):
```

Entering `y` sends an `approve` signal to the running workflow, which then proceeds to LLM synthesis. Entering `n` leaves the workflow at the approval gate until it times out (10 minutes), and the next query can be entered immediately.

The CLI calls `run_research_sync()` (standard mode) or `run_hitl_sync()` (HITL mode) from `src/temporal/client.py`. If the Temporal server or worker is unreachable, the exception is caught and displayed with an actionable message: `Is the Temporal worker running? Run: make temporal-worker`.

## Initialisation Sequence

**Step 1.** Resolve the agent config path. If the file does not exist, print a red error and return.

**Step 2.** Call `load_agent_config(config_path)`. If the YAML is invalid, a Pydantic `ValidationError` propagates to the terminal.

**Step 3.** Print `Loaded agent: {config.name}` in green.

**Step 4.** Create `ExecutionLogger(log_dir)`. The logger creates the directory if it does not exist.

**Step 5.** If `--use-temporal` is set, call `_run_temporal()` and return.

**Step 6.** Attempt to create a `ToolRegistry`. If `tools_dir` does not exist, `tool_registry` is set to `None` and the agent runs in direct LLM mode without printing an error.

**Step 7.** Create `SimpleAgent(config, tool_registry)`.

**Step 8.** Enter either the single-query or interactive execution path.

## Response Display

### Streaming (default)

For all `SimpleAgent` invocations not using `--parallel`, the CLI uses the private `_stream_response()` helper:

```python
for token in agent.stream(query):
    console.print(token, end="", markup=False)
console.print()
```

Tokens are printed as they are generated with no prefix label — the `You:` prompt immediately above provides visual context separation. `markup=False` prevents Rich from interpreting token content as markup. After the generator is exhausted, latency is displayed and execution is logged.

### Parallel Mode

When `--parallel` is set, the CLI wraps `agent.run_parallel(query)` in a Rich spinner and renders the complete response as Markdown once synthesis is finished. This mode does not stream tokens, because the LLM synthesis step follows tool fan-out rather than running concurrently with output printing.

## Logging

After every `SimpleAgent` invocation, the private `_log_execution` function extracts fields from `agent.metrics` and calls `logger.log_execution()`:

```python
logger.log_execution(
    model=metrics.model,
    system_instruction=metrics.system_instruction,
    user_query=query,
    response=response,
    latency_ms=metrics.latency_ms,
    tokens_input=metrics.tokens_input,
    tokens_output=metrics.tokens_output,
    temperature=metrics.temperature,
    top_p=metrics.top_p,
    tools_called=metrics.tools_called,
    tool_responses=metrics.tool_responses,
    tool_success_rate=1.0,
)
```

`tool_responses` is a dict mapping each tool name to its raw string result, captured inside the `SimpleAgent` LangChain wrapper before the result is passed back to the ReAct agent.

For Temporal executions, `_run_temporal` calls `logger.log_execution` directly using `config` fields and the workflow result dict. `router_intent` is set to `"temporal"` for standard Temporal runs and `"temporal-hitl"` for human-in-loop runs, allowing these entries to be distinguished in log analysis. The `tool_responses` field is populated from the workflow's `tool_results` dict.

## Error Handling Summary

| Condition | Behaviour |
|---|---|
| Agent YAML not found | Red error message, return. |
| Invalid agent YAML schema | Pydantic ValidationError propagates to terminal. |
| `tools_dir` not found | `tool_registry = None`; agent runs without tools. |
| Individual tool YAML invalid | ToolRegistry logs error; other tools continue loading. |
| Temporal server unreachable | Exception caught; actionable message displayed. |
| LLM invocation error | Propagates to terminal (not caught at CLI level). |

## Makefile Targets

All targets use `PYTHON := .venv/bin/python` so they work correctly whether or not the shell has the venv activated. `PYTHONDONTWRITEBYTECODE=1` is exported globally — Python will not write `.pyc` files, ensuring code changes are always reflected immediately without stale bytecode.

| Target | Command |
|---|---|
| `make run` | Interactive mode, local ReAct agent. |
| `make run-temporal` | Interactive mode, Temporal workflow per query. |
| `make run-temporal-hitl` | Interactive mode, Temporal workflow with HITL approval gate. |
| `make temporal-worker` | Start the Temporal activity and workflow worker. |
| `make temporal-up` | Start Temporal infrastructure via Docker Compose. |
| `make temporal-down` | Stop Temporal infrastructure. |
| `make temporal-run QUERY="..."` | One-off query via Temporal (no HITL). |
| `make temporal-run-hitl QUERY="..."` | One-off query via Temporal with HITL approval gate. |
| `make install` | Install the project in editable mode via `.venv/bin/python -m pip install -e .`. |
| `make test` | Run the test suite via `.venv/bin/python -m pytest tests/ -v`. |
| `make clean` | Remove all `__pycache__` directories and `.pyc` files outside `.venv`. |

## Future Enhancements

**Query history.** Allow the up-arrow key to recall previous queries in interactive mode.

**Agent listing.** A `--list-agents` flag would scan `config/agentic-reasoning/agents/` and display available configurations.

**Output format options.** A `--output json` flag would emit structured JSON to stdout for pipeline integration.

**Batch execution.** Accepting queries from stdin or a file would enable bulk processing.
