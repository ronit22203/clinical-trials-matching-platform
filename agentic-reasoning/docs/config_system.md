# Configuration System

## Overview

The configuration system is the foundation of the Clinical Agents platform. All agent behavior, model selection, and tool availability are declared in YAML files and validated at load time using Pydantic. The system separates policy (YAML) from execution (Python), so changing how an agent behaves requires editing configuration, not source code.

## Source Location

`src/config_loader.py` contains all Pydantic models for agent configuration and the `load_agent_config` loader function. Full tool configuration schemas live in `src/schemas/tool.py` and are documented separately in data_schemas.md.

## Pydantic Models

### ModelParams

Encapsulates the LLM hyperparameters passed to ChatOllama at agent initialisation.

| Field | Type | Default | Semantics |
|---|---|---|---|
| temperature | float | 0.7 | Randomness of generation. 0.0 is deterministic; 1.0 is highly variable. |
| max_tokens | int or None | None | Maximum response length. None defers to the model default. |
| top_p | float | 0.9 | Nucleus sampling threshold. Only the top tokens summing to this probability are sampled. |
| frequency_penalty | float | 0.0 | Penalises repeated tokens. Range 0.0 to 2.0. |
| presence_penalty | float | 0.0 | Penalises tokens that have already appeared. Range 0.0 to 2.0. |

When `AgentConfig` is constructed without an explicit `model_params` block, Pydantic creates a `ModelParams()` instance with all defaults via `Field(default_factory=ModelParams)`. All fields are passed to `ChatOllama` as keyword arguments using `model_params.model_dump()`.

### ToolConfig (agent-level reference)

Used within `AgentConfig.tools` to declare which tools an agent can access. At this level the schema is intentionally minimal.

| Field | Type | Required | Semantics |
|---|---|---|---|
| name | str | Yes | Identifier matching a tool YAML file in `config/agentic-reasoning/tools/`. |

The full tool configuration schema — including module path, class name, authentication, and rate limits — lives in `src/schemas/tool.py` and is used by `ToolRegistry`, not the config loader.

### AgentConfig

The root object representing a fully validated agent configuration.

| Field | Type | Default | Semantics |
|---|---|---|---|
| name | str | Required | Human-readable label displayed in CLI output. |
| model | str | Required | LLM identifier in `provider/model-name` format (e.g., `ollama/qwen3:1.7b`). |
| system_prompt | str or None | None | System instruction prepended to every conversation turn. |
| model_params | ModelParams | ModelParams() | Hyperparameters forwarded to the LLM client. |
| tools | List[ToolConfig] | [] | Tools available to this agent, referenced by name. |

## The load_agent_config Function

```python
def load_agent_config(path: Path) -> AgentConfig
```

Opens the file at `path`, deserialises it with `yaml.safe_load` to prevent code injection, and passes the resulting dictionary to `AgentConfig(**data)`. Pydantic validates every field. On success, a fully typed `AgentConfig` is returned. On failure, a `ValidationError` is raised with field-level diagnostics.

The CLI wraps the `path.exists()` check before calling this function and displays a red error message if the file is absent. Pydantic errors propagate to the terminal as-is.

## Configuration File Locations

Agent configurations live in `config/agentic-reasoning/agents/`. Each file describes one agent. The default agent loaded by the CLI and `make run` is `config/agentic-reasoning/agents/assistant.yaml`.

Tool configurations live in `config/agentic-reasoning/tools/`. Each file describes one tool. These are loaded by `ToolRegistry`, not `load_agent_config`. See tool_system.md for details.

## Example: Agent YAML to Python Object

Given this YAML file (`config/agentic-reasoning/agents/assistant.yaml`):

```yaml
name: "Simple Assistant"
model: "ollama/qwen3:1.7b"
system_prompt: "You are a senior clinical research assistant."
model_params:
  temperature: 0.2
  max_tokens: 2048
  top_p: 0.9
  frequency_penalty: 0.0
  presence_penalty: 0.0
tools:
  - name: fda_adverse_events
  - name: clinical_trials
  - name: pubmed_search
```

`load_agent_config(Path("config/agentic-reasoning/agents/assistant.yaml"))` produces:

```python
AgentConfig(
    name="Simple Assistant",
    model="ollama/qwen3:1.7b",
    system_prompt="You are a senior clinical research assistant.",
    model_params=ModelParams(
        temperature=0.2,
        max_tokens=2048,
        top_p=0.9,
        frequency_penalty=0.0,
        presence_penalty=0.0,
    ),
    tools=[
        ToolConfig(name="fda_adverse_events"),
        ToolConfig(name="clinical_trials"),
        ToolConfig(name="pubmed_search"),
    ],
)
```

## Validation Error Scenarios

**File not found.** The CLI checks `path.exists()` before calling `load_agent_config` and exits with an error message. No exception is raised from the loader.

**Invalid YAML syntax.** `yaml.safe_load` raises a `yaml.YAMLError`. This propagates to the terminal.

**Missing required field.** Pydantic raises `ValidationError` listing which fields are absent. For example, omitting `model` produces: `1 validation error for AgentConfig — model: Field required`.

**Wrong type.** Passing a string where a float is expected produces: `1 validation error for AgentConfig — model_params.temperature: Input should be a valid number`.

## Adding a New Agent

1. Create a YAML file in `config/agentic-reasoning/agents/` with at minimum `name` and `model`.
2. Add `system_prompt` with domain-specific clinical instructions.
3. Add a `model_params` block if the defaults are unsuitable.
4. List tools by name under `tools:`, each referencing a file in `config/agentic-reasoning/tools/`.
5. Run: `python -m src.cli --agent config/agentic-reasoning/agents/your-agent.yaml "test query"`.

No Python changes are required.

## Future Extensions

The config loader is designed for additive expansion:

**Knowledge base configs.** A `knowledge:` block in AgentConfig would reference RAG sources such as Qdrant collections or document corpora.

**Execution configs.** A `runtime:` block could select between ReAct tool selection and parallel prefetch strategies, allowing different orchestration styles per agent.

**Environment variable substitution.** YAML values could reference environment variables using `${VAR_NAME}` syntax, pre-processed before Pydantic validation.
