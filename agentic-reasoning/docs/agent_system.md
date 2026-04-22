# Agent System

## Overview

The agent system executes natural language queries against a language model and optionally augments responses using registered tools. It provides two execution modes — direct LLM and ReAct with tools — selected automatically at initialisation based on configuration. Comprehensive execution metrics are captured on every run for logging and analysis.

## Source Location

`src/agent.py` contains `ExecutionMetrics` and `SimpleAgent`.

## ExecutionMetrics

`ExecutionMetrics` is an internal data container instantiated at the start of every `SimpleAgent.run()` call. It is populated progressively during execution and read by the CLI after `run()` returns.

### Initialisation

`ExecutionMetrics(config: AgentConfig)` seeds the following fields from the config:

| Field | Source | Description |
|---|---|---|
| model | config.model | LLM identifier string. |
| temperature | config.model_params.temperature | Temperature hyperparameter. |
| top_p | config.model_params.top_p | Top-p hyperparameter. |
| system_instruction | config.system_prompt or "" | The system prompt text. |
| tools_called | [] | Populated as tools are invoked. |
| start_time | None | Set at the beginning of run(). |
| end_time | None | Set in the finally block of run(). |
| tokens_input | 0 | Estimated after LLM invocation. |
| tokens_output | 0 | Estimated after LLM invocation. |
| response | "" | Set after the response is received. |

### The latency_ms Property

Computed as `(end_time - start_time) * 1000`. Returns `0.0` if either timestamp is `None`. Because `end_time` is always set in the `finally` block of `run()`, this value is reliable even when an exception occurs.

## SimpleAgent

`SimpleAgent` is the execution engine. It composes a `ChatOllama` LLM client, an optional `ToolRegistry`, and an optional LangGraph ReAct agent. Callers interact through `run(query)` only.

### Constructor

```python
SimpleAgent(config: AgentConfig, tool_registry: ToolRegistry | None = None)
```

**Step 1.** Store `config` and `tool_registry`.

**Step 2.** Extract the model name by splitting `config.model` on `/` and taking the last part. For `ollama/qwen3:1.7b` this yields `qwen3:1.7b`.

**Step 3.** Create `ChatOllama(model=model_name, **config.model_params.model_dump())`. All `ModelParams` fields are forwarded as keyword arguments.

**Step 4.** Attempt to build a ReAct agent. If `tool_registry` is not `None` and `config.tools` is not empty, call `_build_langchain_tools()`. If that returns a non-empty list, call `create_react_agent(self.llm, lc_tools, prompt=system_prompt)` and store the result as `self._agent`. Otherwise `self._agent` remains `None`.

### _build_langchain_tools

Iterates over `config.tools`. For each entry, calls `tool_registry.get_tool(tool_cfg.name)`. If the tool is found, wraps its `cached_execute` method in a LangChain `@lc_tool` decorator using the tool's `name` and `description`. Inside the wrapper, when the tool is called, the tool name is appended to `self.metrics.tools_called` if not already present. Returns the list of wrapped LangChain tool objects.

Using `cached_execute` means repeated identical tool invocations within the same session are served from the in-memory TTL cache without additional network round trips.

The closure over `_fn` and `_name` is explicit to avoid Python's late-binding behaviour in loops.

### run

```python
def run(self, query: str) -> str
```

**Step 1.** Create a fresh `ExecutionMetrics` instance and record `start_time`.

**Step 2.** Enter a `try` block.

If `self._agent` exists (tool mode): wrap the query in a `HumanMessage`, call `self._agent.invoke({"messages": [msg]})`, and extract `result["messages"][-1].content`.

If `self._agent` is `None` (direct mode): build `messages = [SystemMessage(system_prompt), HumanMessage(query)]` (the `SystemMessage` is omitted if `system_prompt` is `None`), call `self.llm.invoke(messages)`, and extract `.content`.

**Step 3.** Store the response in `metrics.response`.

**Step 4.** Attempt token estimation with `self.llm.get_num_tokens()`. This is wrapped in a secondary `try/except` because not all Ollama models expose this method. Token counts default to 0 if estimation fails.

**Step 5.** Return the response string.

**Step 6** (finally). Record `metrics.end_time`. This runs unconditionally, including on exceptions, ensuring latency is always available for logging.

### stream

```python
def stream(self, query: str) -> Iterator[str]
```

A generator that yields response tokens incrementally as they are produced by the LLM, enabling streaming output in the CLI.

**Direct mode.** Calls `self.llm.stream(messages)` and yields each `chunk.content` string as it arrives.

**Tool mode (ReAct).** Calls `self._agent.stream()` with `stream_mode="messages"`, which yields `(message_chunk, metadata)` tuples. Content tokens from `AIMessageChunk` objects are yielded to the caller. Tool call metadata is used to update `metrics.tools_called`.

In both modes, `self.metrics` is initialised at the start and finalised in the `finally` block (same as `run()`). The complete response is assembled from yielded chunks and stored in `metrics.response` when the generator is exhausted.

**CLI usage.** The CLI's `_stream_response()` helper iterates the generator and prints each token directly to the terminal with `console.print(token, end="", markup=False)`. Logging is called after the generator is exhausted, using `agent.metrics`.

### run_parallel

```python
def run_parallel(self, query: str) -> str
```

Fans out all configured tool calls concurrently using `asyncio.gather`, then passes the aggregated results to the LLM for a single synthesis step. This bypasses the LangGraph ReAct loop entirely.

**When to use.** Suitable for queries where every configured tool is relevant — e.g. a clinical research agent that always fetches from PubMed, openFDA, and ClinicalTrials.gov. The parallel fan-out mirrors what `ClinicalResearchWorkflow` does in Temporal, but without Temporal infrastructure.

**When not to use.** Avoid for agents where tool selection should be conditional on the query. The ReAct loop (via `run()` or `stream()`) remains the default.

**Execution flow.**

```
asyncio.gather(
    asyncio.to_thread(tool_1.cached_execute, query),
    asyncio.to_thread(tool_2.cached_execute, query),
    ...
)
    --> context = aggregated tool results as labeled text
    --> llm.invoke([SystemMessage(system_prompt + context), HumanMessage(query)])
        --> response
```

Each tool's `cached_execute()` runs in a separate thread via `asyncio.to_thread`, so sync tool implementations do not block the event loop. Results are collected into a dict `{tool_name: result_str}` and concatenated into a context block. The LLM is then invoked once with this context embedded in the system message.

**Metrics.** `metrics.tools_called` contains all tool names, `metrics.tool_responses` contains their raw results. Latency covers the full fan-out + synthesis time.

**Fallback.** If no tools are configured, `run_parallel()` delegates to `run()`.

## Direct Mode vs Tool Mode

### Direct Mode

Activated when `tool_registry` is `None` or `config.tools` is empty. Message flow:

```
SystemMessage (if system_prompt set)
HumanMessage (query)
    --> ChatOllama.invoke()
        --> response.content
```

Suitable for question-answering that does not require external data retrieval.

### Tool Mode (ReAct)

Activated when tools are configured. Message flow:

```
HumanMessage (query)
    --> ReAct Agent
        --> LLM decides to call tool(s)
        --> ToolMessage(s) returned
        --> LLM iterates until final answer
            --> result["messages"][-1].content
```

The ReAct agent manages the decision loop autonomously based on the tool descriptions provided during `create_react_agent()`. The system prompt is passed as the `prompt` argument and is embedded in the agent's graph.

## Message Types

**SystemMessage.** Contains the system prompt. Injected before the user turn in direct mode, or passed as the agent prompt in tool mode.

**HumanMessage.** Contains the user query. Always present.

**AIMessage.** The LLM's response. Not constructed manually; returned by LangChain internals.

**ToolMessage.** Contains the result of a tool invocation. Managed automatically by the LangGraph ReAct agent.

## Token Estimation

After the response is received, the agent attempts:

```python
self.metrics.tokens_input = self.llm.get_num_tokens(query)
self.metrics.tokens_output = self.llm.get_num_tokens(response)
```

This is a rough estimate. Not all Ollama models report token counts accurately. The `try/except` silently swallows failures; token fields in the log entry will contain 0 when estimation is unavailable.

## Metrics Access Pattern

The CLI always accesses `agent.metrics` after `run()` returns:

```python
response = agent_instance.run(query)
metrics = agent_instance.metrics
logger.log_execution(
    model=metrics.model,
    latency_ms=metrics.latency_ms,
    tools_called=metrics.tools_called,
    ...
)
```

`self.metrics` is reassigned at the start of each `run()` call, so the last call's metrics are always available on `agent.metrics`.

## Error Handling Behaviour

`SimpleAgent.run()` and `SimpleAgent.stream()` do not have top-level exception handlers. LLM or tool errors propagate to the CLI. The `finally` block guarantees that `metrics.end_time` is always set, making latency data available for logging even when an error occurs. `run_parallel()` similarly propagates LLM invocation errors but catches asyncio task failures per-tool only if the tool itself returns an error string. The CLI catches connection errors for the Temporal path (see cli_interface.md) but not for `SimpleAgent`.

## Future Enhancements

**Conversation memory.** `run()` currently processes each query independently. A conversation buffer would maintain message history across calls for multi-turn interactions.

**Fallback models.** If the primary model is unavailable, a secondary model specified in `AgentConfig` could be tried automatically.
