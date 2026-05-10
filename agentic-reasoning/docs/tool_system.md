# Tool System

## Overview

The tool system provides a plugin architecture for extending agent capabilities with external data sources. Tools are declared in YAML configuration files and loaded at runtime by `ToolRegistry`. Each implementation inherits from `BaseTool`, providing a uniform interface for both the LangGraph ReAct agent and the parallel fan-out path to invoke tools without knowing their concrete types.

## Source Locations

| Component | Path |
|---|---|
| Abstract base class | `src/tools/base.py` |
| Registry | `src/tools/registry.py` |
| Full tool config schema | `src/schemas/tool.py` |
| Tool implementations | `src/tools/implementations/` |
| Tool YAML configs | `config/agentic-reasoning/tools/` |

## BaseTool

`BaseTool` is an abstract class using Python's `ABC` module. All tool implementations must inherit from it and implement `execute`.

### Constructor

```python
BaseTool(config: Dict[str, Any])
```

Accepts and stores the tool's configuration dictionary, which comes directly from the `config:` block in the tool's YAML file. Also initialises two shared resources for all subclasses:

- **`self.session`** — a `requests.Session` instance shared across all calls to this tool instance. Reuses TCP connections via HTTP keep-alive, reducing per-call overhead.
- **`self._cache`** — a `cachetools.TTLCache` keyed on the string representation of the input. Entries expire after `cache_ttl` seconds (default `300`). Maximum number of cached entries is `cache_maxsize` (default `128`). Both values are read from the tool's `config:` block.

### Abstract Method: execute

```python
def execute(self, input: Any) -> Any
```

Subclasses must implement this. Accepts either a plain string or a dictionary. Returns structured data (dict, list) or a plain string on error. The ReAct wrapper converts the return value to a string before passing it back to the LLM. `run_parallel()` wraps this call with `asyncio.to_thread` to avoid blocking the event loop.

### cached_execute

```python
def cached_execute(self, input: Any) -> Any
```

A caching wrapper around `execute()`. Converts `input` to a string key and checks `self._cache`. On a cache hit, returns the stored result without making a network call. On a miss, calls `execute()`, stores the result, and returns it. The `SimpleAgent` ReAct wrapper and `run_parallel()` both call `cached_execute()` rather than `execute()` directly.

**Cache key.** If `input` is already a `str`, it is used as-is. Otherwise `str(input)` is used. Two structurally identical dicts will share a cache entry as long as their string representations match.

**When to bypass the cache.** Call `execute()` directly when fresh data is always required, e.g. in real-time monitoring contexts or when the tool's config sets `cache_ttl: 0`.

### Optional Config Keys

| Key | Default | Semantics |
|---|---|---|
| `cache_ttl` | `300` | Cache TTL in seconds. `0` disables caching (each call invokes `execute()`). |
| `cache_maxsize` | `128` | Maximum number of distinct inputs to cache per tool instance. |

### Properties

**name.** Returns `self.__class__.__name__`. Used by the registry for identification.

**description.** Returns `self.config.get("description", self.name)`. This string is passed to the LangChain `@lc_tool` decorator and used by the ReAct agent to decide when to invoke the tool. It should be written as a task description, not a feature label.

## ToolConfig Schema

Defined in `src/schemas/tool.py`. Validates tool YAML files during registry loading.

| Field | Type | Default | Semantics |
|---|---|---|---|
| name | str | Required | Unique identifier. Must match references in agent configs. |
| description | str or None | None | Human-readable description for the ReAct agent. |
| type | Literal | "function" | One of: `api`, `function`, `vector_db`, `web_search`. |
| module | str | Required | Dot-path to the Python module (e.g., `src.tools.implementations.pubmed`). |
| class_name | str | Required | Class name within the module (e.g., `PubMedTool`). |
| config | dict | {} | Tool-specific parameters passed to the constructor. |
| auth | ToolAuth | ToolAuth() | Authentication config (API key or bearer token). |
| rate_limit | ToolRateLimit | ToolRateLimit() | Rate limit constraints (calls per minute/day). |
| enabled | bool | True | When False, the tool is skipped during registry loading. |

### ToolAuth

| Field | Type | Default | Semantics |
|---|---|---|---|
| type | Literal | "none" | One of: `none`, `api_key`, `bearer`. |
| key | str or None | None | Environment variable name containing the credential. |

### ToolRateLimit

| Field | Type | Default | Semantics |
|---|---|---|---|
| calls_per_minute | int or None | None | Maximum calls per minute. None means unlimited. |
| calls_per_day | int or None | None | Maximum calls per day. None means unlimited. |

Both `auth` and `rate_limit` are parsed but not yet enforced in code.

## ToolRegistry

`ToolRegistry` discovers and instantiates all tools from a directory of YAML files at startup. It is the single source of truth for which tools are available at runtime.

### Initialisation

```python
ToolRegistry(tools_dir: Path)
```

Stores `tools_dir`, initialises an empty `_tools` dict, and calls `_load_all()`.

### _load_all

Calls `tools_dir.glob("*.yaml")` to find all tool config files. For each file, calls `yaml.safe_load()` and checks whether the result is a list (multiple tools per file) or a dict (single tool). Calls `_load_tool(data)` for each entry.

### _load_tool

```
1. Construct ToolConfig(**data). Raises ValidationError on schema violation.
2. If tool_config.enabled is False, return early.
3. Call importlib.import_module(tool_config.module).
4. Call getattr(module, tool_config.class_name) to retrieve the class.
5. Instantiate: instance = tool_class(tool_config.config).
6. Store: self._tools[tool_config.name] = instance.
```

Any exception in steps 1–5 is caught and printed. Loading continues with remaining tools. A partially loaded registry is valid; agents will simply not have access to failed tools.

### Public Methods

**get_tool(name: str) -> BaseTool or None.** Returns the loaded instance by name, or `None` if the tool was not loaded.

**list_tools() -> List[str].** Returns the names of all successfully loaded tools.

## Built-in Implementations

### OpenFDATool

**File.** `src/tools/implementations/openfda.py`

**Purpose.** Queries the FDA adverse event database (`api.fda.gov/drug/event.json`) by drug name and returns structured report summaries.

**Input.** A natural-language query string or a dict with key `"drug"`. The tool calls `_extract_drug_name()` to strip common question prefixes before constructing the API request.

**Output.** `{"total_reports": int, "results": [{"safety_report_id", "serious", "country", "sex", "reactions", "drugs"}]}`.

**API key.** The tool reads the API key with the following precedence: `config["api_key"]` from the YAML config block, then `os.getenv("OPENFDA_API_KEY")` as a fallback. This means the key can be supplied via `.env` without modifying the tool YAML.

**Input sanitisation: _extract_drug_name.** This module-level function uses regular expressions to extract a bare drug or condition name from natural-language input. It strips prefixes such as "side effects of", "adverse events for", "I'm researching", and "what are the contraindications of". Without this step, passing a full sentence to the FDA API would produce a 400 Bad Request error. The function is imported and reused by `ClinicalTrialsTool`.

**Config-driven response parsing.** Field paths (e.g., `["meta", "results", "total"]`) are specified in the YAML `response:` block, allowing schema changes to be absorbed by YAML edits rather than code changes.

**Error handling.** `requests.exceptions.RequestException` is caught; an error string is returned. The LLM can incorporate this in its reasoning.

### PubMedTool

**File.** `src/tools/implementations/pubmed.py`

**Purpose.** Searches PubMed for biomedical literature using the NCBI eUtils API.

**Input.** A search query string, or a dict with key `"query"`. PubMed accepts natural-language queries natively; no sanitisation is applied.

**Output.** A list of article dicts: `{"pmid", "title", "authors", "journal", "pub_date", "url"}`.

**Two-step execution.** First calls `/esearch.fcgi` to retrieve PMIDs matching the query, then calls `/esummary.fcgi` to fetch article metadata for those IDs. Both endpoints are configurable in the YAML.

**Error handling.** Catches `RequestException`; returns an error string.

### ClinicalTrialsTool

**File.** `src/tools/implementations/clinicaltrials.py`

**Purpose.** Queries ClinicalTrials.gov v2 API for studies matching a drug or condition.

**Input.** A natural-language query string or a dict with key `"condition"`. Calls `_extract_drug_name()` (imported from `openfda.py`) before querying the API.

**Output.** A list of study dicts: `{"nct_id", "title", "status", "sponsor", "summary"}`.

**Search parameter.** The YAML config uses `query.term` (full-text search across all study fields). An earlier version used `query.cond` (exact condition name match), which returned empty results for natural-language inputs. `query.term` is more tolerant and works correctly with extracted drug names.

**Nested field navigation.** Uses `_get_nested(obj, path, default)` to safely walk the deeply nested ClinicalTrials.gov API response without raising `KeyError`.

**Error handling.** Catches `RequestException`; returns an error string.

### GraphRAGTool

**File.** `src/tools/implementations/graphrag_tools.py`

**Purpose.** Hybrid retrieval combining Qdrant vector search with Neo4j knowledge-graph enrichment. Vector search casts a semantic net over ingested document chunks; the graph layer adds structured entity–relation–entity triples whose head or tail matches keywords in the query.

**Dependencies.** Requires `qdrant-client`, `neo4j`, and `sentence-transformers`. All three are imported lazily (on first `execute()` call), so the tool can be registered without these packages being installed. Install with `uv pip install qdrant-client neo4j sentence-transformers`, or run `make download-models` to also pre-warm the embedding model.

**Input.** A natural-language query string, or a dict with key `"query"`. An empty string returns an error string.

**Output.** A dict:
```python
{
    "query": str,
    "keywords": List[str],          # extracted from query, used for graph matching
    "vector_results": [             # from Qdrant
        {"score", "content", "source", "chunk_id", "chunk_index", "context"}
    ],
    "graph_facts": List[str],       # from Neo4j, e.g. "ASPIRIN --[TREATS]--> HEADACHE"
}
```

**Two-stage retrieval.**

*Stage 1 — Vector search.* The query is encoded by the SentenceTransformer model specified in `embedding_model`. The resulting vector is queried against the Qdrant collection specified in `collection`. The top `limit` results are returned with their payloads.

*Stage 2 — Graph enrichment.* `_extract_keywords()` strips stop words from the query and returns up to 5 meaningful tokens. A parameterised Cypher query matches any entity node whose `name` property contains any of those keywords (case-insensitive `toLower CONTAINS`). Up to `neo4j_limit` triples are returned.

**Keyword extraction: `_extract_keywords`.** A module-level function that strips a built-in set of English stop words and words shorter than 3 characters, returning the first `max_keywords` (default 5) remaining tokens. This avoids submitting full sentences to the Cypher query while still matching meaningful entity names.

**Lazy client initialisation.** `_qdrant_client()`, `_embedder_model()`, and `_neo4j_driver()` are property-style accessors that instantiate their clients on first access and cache them on `self`. This means tool registration (at CLI startup) is instantaneous; the network connections and model load happen only when the tool is first invoked in a session.

**Model caching.** `SentenceTransformer` is constructed with `cache_folder` pointing to `data/models/` (from `config["model_cache_dir"]`, defaulting to `"data/models"`). On first use the model is downloaded from HuggingFace and written to `data/models/`. Subsequent process starts load from disk. Pre-warm with `make download-models`.

**Config keys.**

| Key | Default | Semantics |
|---|---|---|
| `qdrant_url` | — | Qdrant HTTP URL, e.g. `http://localhost:6333` |
| `collection` | — | Qdrant collection name, e.g. `medical_papers` |
| `neo4j_uri` | — | Neo4j bolt URI, e.g. `bolt://localhost:7687` |
| `neo4j_username` | — | Neo4j username |
| `neo4j_password` | — | Neo4j password |
| `embedding_model` | — | HuggingFace model ID, e.g. `BAAI/bge-small-en-v1.5` |
| `model_cache_dir` | `"data/models"` | Local directory for model download cache |
| `limit` | `3` | Number of Qdrant vector search results |
| `neo4j_limit` | `10` | Max Neo4j triples per query |

**Error handling.** Vector search failures return an `"Error: ..."` string. Neo4j failures are caught and logged at `WARNING` level; the tool returns an empty `graph_facts` list rather than failing the whole retrieval.

**Infrastructure.** Qdrant and Neo4j can be started with `make graphrag-up` (Docker Compose via `infra/docker-compose.graphrag.yml`). Qdrant dashboard: `http://localhost:6333/dashboard`. Neo4j browser: `http://localhost:7474` (credentials: `neo4j` / `testpassword`).

### MCPTool (mcp_filesystem)

**File.** `src/tools/implementations/mcp_tool.py`

**Config file.** `config/agentic-reasoning/tools/mcp_filesystem.yaml`

**Purpose.** Read and write files via the Model Context Protocol (MCP) filesystem server (`@modelcontextprotocol/server-filesystem`). Allows the ReAct agent to persist output — for example, saving a comprehensive research summary report to disk.

**Input.** A file path string (for `write_file`, also requires content). The `default_arg_key` config key controls which MCP argument the tool's input string is mapped to.

**MCP operation.** Configured with `tool_name: "write_file"` — the agent uses this tool to save generated reports. Change `tool_name` to `"read_file"` or `"list_directory"` to expose different filesystem operations to the agent.

**Allowed directories.** The MCP server enforces an allowlist of directories it will read from or write to. The current config allows:

```yaml
args: ["-y", "@modelcontextprotocol/server-filesystem",
       "/Users/ronitsaxena/Desktop",
       "/Users/ronitsaxena/Developer/clinical_agents"]
```

Attempts to access paths outside these directories return an `"Access denied"` error string. Add additional paths to the `args` list in `config/agentic-reasoning/tools/mcp_filesystem.yaml` to expand access.

**Runtime dependency.** Requires Node.js and `npx` on the system PATH. The MCP server is launched as a subprocess via `stdio` transport on first tool invocation.

**Error handling.** MCP errors (access denied, file not found) are returned as error strings that the ReAct agent can reason about and report to the user.

## Common Implementation Patterns

**Input flexibility.** Every tool checks `isinstance(input, str)` and falls back to `input.get("key", "")` to accept both string and dict inputs.

**Connection pooling via shared session.** All tools use `self.session.get(...)` (a `requests.Session` initialised in `BaseTool.__init__`) rather than calling `requests.get(...)` directly. The session reuses TCP connections across calls to the same host, reducing per-request latency and avoiding repeated TLS handshakes.

**Result caching via cached_execute.** The `SimpleAgent` ReAct wrapper calls `cached_execute()` instead of `execute()` for every tool invocation. Repeat queries with identical inputs are served from the in-memory TTL cache without making a network round trip.

**Drug name extraction.** `_extract_drug_name()` in `openfda.py` is a shared utility that normalises natural-language queries into clean identifiers for APIs that do not accept full sentences. Tools that call clinical APIs import this function rather than duplicating the logic.

**Config-driven field mapping.** Response field names and nested paths are specified in the YAML `response.fields` block. Tools read these at runtime rather than hardcoding field names, making them resilient to minor API changes.

**Nested dict navigation helper.** `_get_nested(obj, path, default)` walks a list of keys through nested dicts, returning `default` if any level is missing.

**Lazy client initialisation.** Tools with heavy dependencies (network clients, ML models) store clients as `None` on `__init__` and instantiate them on first use via private accessor methods. This keeps tool registration at startup instantaneous and isolates connection failures to the first invocation, not the startup phase. `GraphRAGTool` demonstrates this pattern with `_qdrant_client()`, `_embedder_model()`, and `_neo4j_driver()`.

**Error-as-string return.** Tools never raise exceptions to callers. Network errors are returned as descriptive strings so the LLM agent can include the error context in its reasoning.

## Tool Development Guide

To add a new clinical data source:

**Step 1.** Create `src/tools/implementations/my_tool.py`. Inherit from `BaseTool`. Implement `execute(self, input: Any) -> Any`. Use `self.session.get(...)` for HTTP calls (connection pooling is provided automatically by `BaseTool`). Follow the input-flexibility and error-as-string patterns above.

**Step 2.** Create `config/agentic-reasoning/tools/my_tool.yaml`. Set `module` to the dot-path of your new file and `class_name` to your class. Write a `description` that clearly states what input the tool expects, since the ReAct agent reads this when deciding whether to call the tool.

**Step 3.** Add `- name: my_tool` to the `tools:` list in the relevant agent YAML.

**Step 4.** Verify loading by running the CLI and observing `Loaded tool: my_tool` in the console output.

**Step 5.** Test the tool directly:

```python
from src.tools.implementations.my_tool import MyTool
tool = MyTool({"base_url": "...", "timeout": 10})
print(tool.execute("test input"))
```

## Integration with Parallel Execution

`run_parallel()` fans out `tool.cached_execute(query)` calls concurrently via `asyncio.to_thread` and `asyncio.gather`. This means:

All tools must be safe to execute concurrently within a single process.
The tool configuration directory must be accessible from the CLI or server working directory.
Tool instances can share in-process state such as the TTL cache or `requests.Session`, but each new agent process starts with fresh instances.
