# Model Context Protocol (MCP) Integration

This project supports the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/), allowing agents to use tools provided by external MCP servers. This enables integration with local resources (filesystem, databases) and remote services without writing custom Python code for each tool.

## Architecture

The integration consists of two main components:

1.  **`MCPServerManager`** (`src/tools/mcp_manager.py`): A singleton that manages connections to MCP servers. It handles the lifecycle of server processes (stdio) or connections (SSE) and ensures efficient resource usage by deduplicating connections to the same server configuration.
2.  **`MCPTool`** (`src/tools/implementations/mcp_tool.py`): A generic tool implementation that wraps an MCP tool. It translates the internal tool interface to MCP protocol calls.

## Configuration

To use an MCP tool, you need to define it in a tool configuration YAML file, just like native tools.

### Example: Filesystem Tool

Create a file in `config/agentic-reasoning/tools/` (e.g., `config/agentic-reasoning/tools/mcp_filesystem.yaml`):

```yaml
name: mcp_filesystem
description: Read files from the allowed directory using MCP filesystem server.
module: src.tools.implementations.mcp_tool
class_name: MCPTool
config:
  # The name of the tool as exposed by the MCP server
  tool_name: "read_file"
  
  # Optional: If the tool takes a single argument but the agent provides a string,
  # map the string to this argument key.
  default_arg_key: "path"
  
  # Server configuration (Stdio)
  server:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/allowed/directory"]
    env:
      NODE_ENV: "production"
```

### Server Configuration Options

The `server` block supports the following keys:

*   **`command`** (required for stdio): The executable to run (e.g., `npx`, `python`, `docker`).
*   **`args`** (optional): A list of arguments to pass to the command.
*   **`env`** (optional): A dictionary of environment variables to set for the server process.

## Usage in Agents

Once the tool is configured, add its name to your agent's configuration file:

```yaml
# config/agentic-reasoning/agents/my_agent.yaml
name: my_agent
model: ollama/llama3
tools:
  - name: mcp_filesystem
  - name: other_native_tool
```

The agent will now be able to call `mcp_filesystem` (which maps to `read_file` on the MCP server).

## Troubleshooting

*   **Server Process**: The `MCPServerManager` starts the server process when the first tool requiring it is called. The process remains alive for the duration of the application.
*   **Connection Errors**: If the server fails to start or crashes, the tool execution will return an error message to the model, allowing it to retry or inform the user.
*   **Dependencies**: Ensure that the MCP server's dependencies (e.g., `npm`, `npx`, specific Python packages) are installed and available in the system PATH.
