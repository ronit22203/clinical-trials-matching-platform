# Logging System

## Overview

The logging system captures structured execution metadata for every agent interaction and persists it as JSON. Logs serve as an audit trail, a performance analysis dataset, and a debugging resource. Every execution produces an individual JSON file and an entry in a cumulative JSONL summary file.

## Source Location

`src/logging_handler.py`

## ExecutionLogger

### Initialisation

```python
ExecutionLogger(log_dir: str = "log")
```

Creates the log directory if it does not exist. Generates a UUID for `execution_id` and records an ISO 8601 `timestamp`. These values are shared across all log entries produced by this logger instance. Also runs `git rev-parse HEAD` once and caches the result as `_git_commit` — subsequent `log_execution()` calls read from this cached value rather than spawning a new subprocess.

### Attributes

| Attribute | Type | Description |
|---|---|---|
| log_dir | Path | Resolved path to the log directory. |
| execution_id | str | UUID4 string identifying this session. |
| timestamp | str | ISO 8601 creation timestamp. |
| _git_commit | str or None | Git commit SHA, fetched once at init. `None` if Git is unavailable. |

## Log Entry Schema

Every call to `log_execution()` produces a JSON object with the following fields:

| Field | Type | Description |
|---|---|---|
| timestamp | str | ISO 8601 timestamp from logger creation. |
| execution_id | str | UUID linking related log files. |
| model | str | Model identifier (e.g., `ollama/qwen3:1.7b`). |
| system_instruction | str | System prompt, truncated to 200 characters. |
| user_query | str | The user's input. |
| response | str | The agent's response, truncated to 500 characters. |
| latency_ms | float | Execution time in milliseconds, rounded to 2 decimal places. |
| tokens_input | int | Estimated input token count. |
| tokens_output | int | Estimated output token count. |
| tokens_total | int | Sum of input and output tokens. |
| temperature | float | Temperature hyperparameter. |
| top_p | float | Top-p hyperparameter. |
| tools_called | List[str] | Names of tools invoked during execution. |
| tool_responses | dict (optional) | Raw string result from each tool, keyed by tool name. Present for both SimpleAgent and Temporal executions. |
| tool_success_rate | float | Fraction of tools that succeeded, rounded to 2 decimal places. |
| git_commit | str (optional) | Current Git commit SHA, if available. |
| router_confidence | float (optional) | Routing confidence score, if applicable. |
| router_intent | str (optional) | Intent classification. `"temporal"` for standard Temporal runs; `"temporal-hitl"` for human-in-loop runs. |
| memory_snapshot | dict (optional) | Conversation memory state, if applicable. |

### Field Truncation

`system_instruction` is truncated at 200 characters and `response` at 500 characters. Both append `"..."` when cut. Truncation prevents log files from ballooning on long system prompts or verbose responses while retaining sufficient context for debugging.

### Numeric Precision

`latency_ms`, `tool_success_rate`, and `router_confidence` are rounded to 2 decimal places using Python's built-in `round()`.

## Git Commit Tracking

`_fetch_git_commit()` is called once during `__init__`. It runs `git rev-parse HEAD` as a subprocess in the project root with a 5-second timeout and caches the result as `_git_commit`. The public `get_git_commit()` method returns this cached value. If Git is unavailable or the command fails, `_git_commit` is `None` and the `git_commit` field is omitted from all log entries. Fetching the hash at construction time (rather than on each `log_execution()` call) eliminates the per-run subprocess overhead.

## File Persistence

### Fire-and-Forget Writes

`log_execution()` constructs the log entry dict synchronously, then dispatches file I/O to a daemon `threading.Thread`. This means the method returns immediately — it never blocks the response path regardless of disk speed. Writes are best-effort: if the process exits before the thread completes, in-flight log entries may be lost. This trade-off is acceptable for interactive CLI use where process lifetime is longer than a single log write.

### Individual Files

Each `log_execution()` call writes a complete, indented JSON object to:

```
log/{execution_id}.json
```

The file is human-readable (2-space indentation) and self-contained. It can be opened and parsed independently without reference to any other file.

### Summary Log (JSONL)

After writing the individual file, the same entry is appended as a single minified line to:

```
log/summary.jsonl
```

The file uses JSON Lines format: one complete JSON object per line, no trailing comma, no wrapping array. New entries are appended with mode `"a"` so existing entries are never rewritten. This format supports efficient streaming, `grep`, and `jq` analysis.

## log_execution Signature

```python
def log_execution(
    self,
    model: str,
    system_instruction: str,
    user_query: str,
    response: str,
    latency_ms: float,
    tokens_input: int = 0,
    tokens_output: int = 0,
    temperature: float = 0.7,
    top_p: float = 0.9,
    tools_called: Optional[List[str]] = None,
    tool_responses: Optional[Dict[str, Any]] = None,
    tool_success_rate: float = 1.0,
    router_confidence: Optional[float] = None,
    router_intent: Optional[str] = None,
    memory_snapshot: Optional[Dict[str, Any]] = None,
) -> None
```

Optional fields are omitted from the log entry entirely when `None`.

## Integration Points

### SimpleAgent Path

The CLI calls `_log_execution(agent, query, response, logger)` after every `agent.run()`. This extracts all values from `agent.metrics` and forwards them to `logger.log_execution()`. The `tool_responses` field is populated by the LangChain tool wrapper in `SimpleAgent`, which captures each tool's raw return value before passing it back to the ReAct loop.

### Temporal Path

The CLI's `_run_temporal()` calls `logger.log_execution()` directly using values from `AgentConfig` and the returned workflow result dict. `router_intent` is set to `"temporal"` for standard runs and `"temporal-hitl"` for human-in-loop runs. The `tool_responses` field is populated from the workflow's `tool_results` dict, which contains raw API responses from each parallel tool activity.

## Log Analysis Examples

Average latency across all executions:

```bash
cat log/summary.jsonl | jq '.latency_ms' | awk '{s+=$1; c++} END {print s/c " ms"}'
```

Most frequently called tools:

```bash
cat log/summary.jsonl | jq -r '.tools_called[]' | sort | uniq -c | sort -rn
```

All executions for a specific Git commit:

```bash
grep '"git_commit": "abc123"' log/summary.jsonl | jq '.user_query'
```

All Temporal workflow executions:

```bash
cat log/summary.jsonl | jq 'select(.router_intent | startswith("temporal"))'
```

All human-in-loop executions:

```bash
cat log/summary.jsonl | jq 'select(.router_intent == "temporal-hitl")'
```

Raw tool responses for a specific query:

```bash
cat log/summary.jsonl | jq 'select(.user_query | contains("semaglutide")) | .tool_responses'
```

## Future Extensions

**Error classification.** Adding an `error_type` field would allow categorisation of execution failures distinct from successful responses containing error context.

**Log rotation.** A configurable `max_entries` or age-based cleanup policy would prevent unbounded growth of `summary.jsonl`.

**External log sinks.** The JSON schema is compatible with ELK Stack, AWS CloudWatch, Datadog, and similar platforms. Extending `log_execution()` to POST entries to an external endpoint would enable centralised observability.

**Conversation context.** Populating `memory_snapshot` with conversation history would make multi-turn interactions fully reconstructible from logs.
