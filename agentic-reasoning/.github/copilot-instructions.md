# Copilot Instructions for Clinical Agents

## Quick Reference

**Makefile topology:** use the single repo-root Makefile. The module-local Makefile is gone; use root `make reasoning-*` targets.

### Running & Testing
- **Run the CLI**: `python -m src.cli --agent local_assistant "your query"`
- **Interactive mode**: `python -m src.cli --agent local_assistant` (type queries, then `exit`)
- **Install dependencies**: `pip install -e .` or `make reasoning-install`
- **Run all tests**: `pytest tests/ -v` or `make reasoning-test`
- **Run a single test**: `pytest tests/test_agent.py::TestSimpleAgentNoTools::test_run_returns_llm_content -v`
- **Note**: The `clinical-agents` script entry point has module resolution issues; always use `python -m src.cli`

## Architecture Overview

### Config-Driven Design
This is a **configuration-first** platform where behavior is defined in YAML, not Python:
- **Unified config** in `../config/app.yaml` defines agent names, models, system prompts, model parameters, tool definitions, and service settings

The core engine loads configs and initializes components—changes to agent behavior typically require editing YAML, not Python code. Agent configs reference tools by name; the tool registry dynamically loads implementations.

### Core Components
1. **Config Loader** (`src/config_loader.py`)
   - Loads YAML agent and tool configs using Pydantic for validation
   - Returns `AgentConfig` objects with name, model, system_prompt, model_params, and tools list

2. **Tool Registry** (`src/tools/registry.py`)
   - Dynamically loads tool implementations from `src/tools/implementations/`
   - Returns tool instances with `execute()` and `description` attributes
   - Tool implementations: `pubmed.py`, `openfda.py`, `clinicaltrials.py`, `mcp_tool.py`, `graphrag_tools.py`

3. **SimpleAgent** (`src/agent.py`)
   - Wraps LangChain's ChatOllama LLM
   - Conditionally creates LangGraph ReAct agent when tools are configured
   - Tracks execution metrics (latency, tokens, tools called) — always logged to `log/`

4. **CLI** (`src/cli.py`)
   - Click-based interface
   - Uses Rich for formatted console output

### Tech Stack
- **LLM Runtime**: LangChain + ChatOllama (local Ollama, extensible via LiteLLM)
- **Orchestration**: LangGraph ReAct for tool-calling
- **Config Format**: YAML + Pydantic validation
- **CLI Framework**: Click + Rich
- **Runtime**: Python 3.12+

## Key Conventions

### YAML Configuration
- **Agent configs** must have: `name`, `model` (format: `provider/model-name`), optional `system_prompt`, optional `model_params`, optional `tools`
  - Models follow `ollama/model-name` convention (e.g., `ollama/qwen3:1.7b`)
  - `model_params`: `temperature`, `max_tokens`, `top_p`, `frequency_penalty`, `presence_penalty`
  - `tools` is a list of tool references by name (e.g., `- name: fda_adverse_events`)

- **Tool configs** must have: `name`, `description`, `type` (api/function/mcp), `module`, `class_name`, `config`
  - `module` points to the implementation (e.g., `src.tools.implementations.pubmed`)
  - `class_name` is the implementation class (e.g., `PubMedTool`)
  - For MCP tools, add `tool_name` and `default_arg_key` under `config`

### Tool Implementation Pattern
All tools inherit from `BaseTool` (`src/tools/base.py`) and implement `execute(input) -> Any`. Return `"Error: ..."` strings on failure (not exceptions) so the LLM can handle gracefully. API tools should mock `requests.get` in tests — see `tests/test_tools.py` for the pattern.

### Code Organization
- `src/config_loader.py` — Pydantic models: `AgentConfig`, `ToolConfig`, `ModelParams`
- `src/tools/base.py` — `BaseTool` abstract class
- `src/tools/registry.py` — dynamic tool loader
- `src/tools/implementations/` — clinical tool implementations
- `src/agent.py` — `SimpleAgent`, `ExecutionMetrics`
- `src/cli.py` — Click CLI entry point
- `src/logging_handler.py` — `ExecutionLogger` for audit trails
- `src/schemas/` — Pydantic models for tool configuration

### Dependencies
- `pyproject.toml` with setuptools; pytest is included in dependencies
- Environment variables via `python-dotenv` — copy `.env` for API keys

## Common Patterns

### Adding a New Tool
1. Create `src/tools/implementations/my_tool.py` inheriting from `BaseTool`
2. Add a tool entry under `agentic_reasoning.tools` in `../config/app.yaml` with `module` and `class_name`
3. Add `- name: my_tool` to the target agent entry in `agentic_reasoning.agents` inside `../config/app.yaml`
4. Add tests in `tests/test_tools.py` mocking `requests.get`

### Adding a New Agent
1. Create a new agent entry under `agentic_reasoning.agents` in `../config/app.yaml` with name, model, system_prompt, and tool references
2. Run with `python -m src.cli --agent my_agent "query"`

## Notes
- Clinical domain context is baked into system prompts — keep them domain-specific
- LangGraph ReAct agent is only created when tools are configured in the agent config
- Parallel tool execution via `run_parallel()`: all tools fan out concurrently with `asyncio.gather`; timeouts are handled per-tool
- Expect rapid architectural changes; follow config-first pattern: define YAML structure before implementing logic
