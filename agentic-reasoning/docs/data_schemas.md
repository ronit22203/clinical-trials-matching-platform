# Data Schemas

## Overview

All structured configuration and data transfer objects in the Clinical Agents platform are defined as Pydantic models. Pydantic provides runtime type checking, automatic coercion of compatible types, and descriptive validation errors that help identify misconfigured YAML files quickly.

Schemas are split across two files:

`src/config_loader.py` — agent-level schemas (ModelParams, ToolConfig reference, AgentConfig).

`src/schemas/tool.py` — tool-level schemas (ToolAuth, ToolRateLimit, ToolConfig).

## Agent Configuration Schemas

### ModelParams

Location: `src/config_loader.py`

Encapsulates the LLM hyperparameters forwarded to `ChatOllama` at agent initialisation. All fields have defaults, so a `model_params:` block in YAML is optional.

| Field | Type | Default | Range | Semantics |
|---|---|---|---|---|
| temperature | float | 0.7 | 0.0 to 2.0 | Sampling randomness. 0.0 is fully deterministic. |
| max_tokens | int or None | None | Positive integer | Maximum response length. None defers to model default. |
| top_p | float | 0.9 | 0.0 to 1.0 | Nucleus sampling threshold. |
| frequency_penalty | float | 0.0 | 0.0 to 2.0 | Repeated token suppression. |
| presence_penalty | float | 0.0 | 0.0 to 2.0 | New topic encouragement. |

`ModelParams` is passed to `ChatOllama` via `model_params.model_dump()`, which produces a plain dict of all fields. Pydantic does not enforce the numeric ranges above; they are documented for semantic correctness.

### ToolConfig (agent-level reference)

Location: `src/config_loader.py`

Used inside `AgentConfig.tools` to declare which tools an agent may access. This is a thin reference model; full tool configuration is in `src/schemas/tool.py`.

| Field | Type | Required | Semantics |
|---|---|---|---|
| name | str | Yes | Identifier matching the `name` field in a tool YAML config. |

### AgentConfig

Location: `src/config_loader.py`

The root object returned by `load_agent_config()`. Represents a fully validated agent configuration.

| Field | Type | Default | Semantics |
|---|---|---|---|
| name | str | Required | Human-readable label shown in CLI output. |
| model | str | Required | LLM identifier in `provider/model-name` format. |
| system_prompt | str or None | None | System instruction prepended to every turn. |
| model_params | ModelParams | ModelParams() | LLM hyperparameters. Created with all defaults if omitted from YAML. |
| tools | List[ToolConfig] | [] | Tools the agent may access, referenced by name. |

**Model identifier convention.** The `model` field uses the format `provider/model-name`. The provider prefix is stripped by `SimpleAgent` (`config.model.split('/')[-1]`) before being passed to `ChatOllama`. Current examples use `ollama/qwen3:1.7b`.

## Tool Configuration Schemas

### ToolAuth

Location: `src/schemas/tool.py`

Defines authentication method for tools that require API credentials.

| Field | Type | Default | Semantics |
|---|---|---|---|
| type | Literal | "none" | Authentication strategy. One of: `none`, `api_key`, `bearer`. |
| key | str or None | None | Environment variable name holding the credential (not the value itself). |

**Important.** The `key` field stores the environment variable name (e.g., `"PUBMED_API_KEY"`), not the actual secret value. Tool implementations are responsible for resolving `os.environ[auth.key]` at execution time. Rate limiting and authentication fields are parsed but not yet enforced in the current codebase.

### ToolRateLimit

Location: `src/schemas/tool.py`

| Field | Type | Default | Semantics |
|---|---|---|---|
| calls_per_minute | int or None | None | Maximum API calls allowed per minute. None means unlimited. |
| calls_per_day | int or None | None | Maximum API calls allowed per day. None means unlimited. |

### ToolConfig (full)

Location: `src/schemas/tool.py`

Validated by `ToolRegistry._load_tool()` for each tool YAML file.

| Field | Type | Default | Semantics |
|---|---|---|---|
| name | str | Required | Unique tool identifier. Must be unique across all YAML files in `config/agentic-reasoning/tools/`. |
| description | str or None | None | Description used by the ReAct agent to decide when to call this tool. |
| type | Literal | "function" | Tool category: `api`, `function`, `vector_db`, or `web_search`. |
| module | str | Required | Python module dot-path (e.g., `src.tools.implementations.openfda`). |
| class_name | str | Required | Class name within the module (e.g., `OpenFDATool`). |
| config | dict | {} | Arbitrary tool-specific parameters passed to the constructor. |
| auth | ToolAuth | ToolAuth() | Authentication configuration. |
| rate_limit | ToolRateLimit | ToolRateLimit() | Rate limiting constraints. |
| enabled | bool | True | When False, the tool is skipped during registry loading. |

**The `config` field.** This is an open-ended dictionary. Pydantic validates that it is a dict but does not validate its contents. Each tool implementation is responsible for reading and validating its own config keys. The `config` dict is passed directly to the tool's constructor.

**The `type` field.** Currently used for documentation and future routing logic. The registry instantiates all tools the same way regardless of type. Future versions may use this to route to different loading strategies (e.g., vector database connectors).

## Example: Full Tool Config Object

Given this YAML (`config/agentic-reasoning/tools/fda_adverse_events.yaml`):

```yaml
name: fda_adverse_events
description: "Query FDA adverse event reports by drug name."
type: api
module: src.tools.implementations.openfda
class_name: OpenFDATool
config:
  base_url: "https://api.fda.gov"
  endpoint: "/drug/event.json"
  limit: 5
  timeout: 10
auth:
  type: none
rate_limit:
  calls_per_minute: 240
enabled: true
```

`ToolRegistry._load_tool(data)` produces:

```python
ToolConfig(
    name="fda_adverse_events",
    description="Query FDA adverse event reports by drug name.",
    type="api",
    module="src.tools.implementations.openfda",
    class_name="OpenFDATool",
    config={
        "base_url": "https://api.fda.gov",
        "endpoint": "/drug/event.json",
        "limit": 5,
        "timeout": 10,
    },
    auth=ToolAuth(type="none", key=None),
    rate_limit=ToolRateLimit(calls_per_minute=240, calls_per_day=None),
    enabled=True,
)
```

## Validation Error Reference

| Scenario | Pydantic Error Example |
|---|---|
| Missing required field | `1 validation error for AgentConfig — model: Field required` |
| Wrong type | `1 validation error for ModelParams — temperature: Input should be a valid number` |
| Invalid literal | `1 validation error for ToolConfig — type: Input should be 'api', 'function', 'vector_db' or 'web_search'` |
| Invalid auth type | `1 validation error for ToolAuth — type: Input should be 'none', 'api_key' or 'bearer'` |

## Schema Extension Guidelines

When adding new fields to any schema:

Use `Optional[T]` with a sensible default for backward-compatible additions.
Use `Field(default_factory=...)` for mutable defaults (lists, dicts, nested models).
Document the semantics of every new field in this file and in the relevant YAML comment.
Add a corresponding entry to the "Future Extensions" section of config_system.md or tool_system.md.
Do not add fields to Pydantic models that are not used by at least one component, to avoid schema drift.
