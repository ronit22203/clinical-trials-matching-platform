# Documentation Index

This directory contains comprehensive documentation for the Clinical Agents codebase. Each document covers a distinct separation of concern, describing component internals, data flows, and integration points in detail.

## Documents

**config_system.md**
How YAML configuration files are loaded, validated with Pydantic, and transformed into typed Python objects. Covers AgentConfig, ToolConfig, ModelParams, and the load_agent_config function.

**agent_system.md**
The agent execution engine. Describes SimpleAgent, ExecutionMetrics, the two execution modes (direct LLM and ReAct with tools), message construction, token estimation, and graceful error handling.

**tool_system.md**
The plugin architecture for extending agent capabilities. Covers BaseTool, ToolRegistry dynamic loading, the four built-in clinical tool implementations (PubMed, OpenFDA, ClinicalTrials.gov, GraphRAG hybrid retrieval), lazy client initialisation for heavy dependencies, and the guide for adding new tools.

**cli_interface.md**
The Click-based command-line interface. Documents all options and arguments (including `--use-temporal` and `--human-in-loop`), three execution modes (local ReAct, Temporal auto-synthesise, Temporal with human-in-loop review), Rich console output, error handling, logging integration, and all Makefile targets.

**logging_system.md**
Structured execution logging. Documents ExecutionLogger, the full JSON log entry schema including `tool_responses` and `router_intent`, individual and JSONL summary file persistence, Git commit tracking, field truncation, and log analysis examples.

**data_schemas.md**
All Pydantic models used across the system. Covers ModelParams, AgentConfig, ToolConfig (simple and full), ToolAuth, and ToolRateLimit, including field semantics and validation rules.

**temporal_system.md**
The Temporal.io workflow integration. Covers the workflow definition with human-in-the-loop signal and query, activities with input sanitisation, worker, client helpers (start, poll, approve, HITL sync), parallel tool execution, retry policies, Docker Compose setup, and all CLI modes including interactive Temporal sessions.

**architecture.md**
System-wide architecture. Covers design principles, component relationship graph, full data flow for direct and tool-augmented queries, the two data directory locations (`data/` and `infra/data/`), design patterns, fault tolerance, and future evolution targets.

## How to Use This Documentation

Start with architecture.md for the big-picture view of how all components interact. Then navigate to the document for the specific concern you are working on.

When writing a new agent configuration, read config_system.md and agent_system.md.

When adding a new clinical tool, read tool_system.md for the BaseTool interface and registration process.

When building or extending the Temporal workflow path, read temporal_system.md.

When analysing execution logs or extending the logging schema, read logging_system.md.

When modifying Pydantic schemas or adding new validation, read data_schemas.md.

## Key Design Principles

**Configuration-First.** Behavior is defined in YAML files. Code changes are needed only when introducing new capability types, not when changing how agents behave.

**Separation of Concerns.** Each module has one responsibility. Config loading, agent execution, tool invocation, workflow orchestration, and logging are fully decoupled.

**Dynamic Loading.** Tools and agents are discovered and loaded at runtime from YAML, not hardcoded.

**Metric-Driven Observability.** Every execution produces a structured JSON log entry capturing latency, tokens, tools called, model parameters, and Git commit.

**Minimal MVP Foundation.** The codebase is intentionally simple. Complexity is added incrementally as patterns are proven.
