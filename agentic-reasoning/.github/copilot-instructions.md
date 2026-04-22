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

### Temporal Workflow Mode
- **Start infrastructure**: `make reasoning-temporal-up` (Docker; UI at http://localhost:8080)
- **Start worker** (separate terminal): `make reasoning-temporal-worker`
- **Run with Temporal**: `make reasoning-temporal-run QUERY="your query"`
- **Human-in-the-loop**: `make reasoning-temporal-run-hitl QUERY="your query"` (pauses for approval signal after tool calls)
- **Stop infrastructure**: `make reasoning-temporal-down`

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
   - Click-based interface with `--use-temporal` and `--human-in-loop` flags
   - Uses Rich for formatted console output

5. **Temporal layer** (`src/temporal/`)
   - `workflows.py` — `ClinicalResearchWorkflow`: runs all tools in parallel, optional HITL approval gate
   - `activities.py` — `execute_tool_activity`, `synthesize_results_activity` (all I/O lives here)
   - `worker.py` — standalone worker process; task queue: `clinical-research-queue`, host: `localhost:7233`
   - `client.py` — `run_research_sync` / `run_hitl_sync` helpers called by the CLI

### Tech Stack
- **LLM Runtime**: LangChain + ChatOllama (local Ollama, extensible via LiteLLM)
- **Orchestration**: Temporal.io with LangGraph ReAct for tool-calling
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

### Temporal Workflow Constraint
Temporal workflows (`src/temporal/workflows.py`) **must be deterministic** — no I/O, no randomness, no blocking calls, no direct time calls. All side effects (API calls, LLM inference) belong in activities. Use `workflow.unsafe.imports_passed_through()` for importing non-deterministic modules at the top of the file.

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
- `src/temporal/` — Temporal workflow, activities, worker, client
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
- Temporal tools run in parallel within `ClinicalResearchWorkflow`; timeouts: tools 30s, synthesis 120s, HITL approval 10min
- Expect rapid architectural changes; follow config-first pattern: define YAML structure before implementing logic
