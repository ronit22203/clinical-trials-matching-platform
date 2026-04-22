from typing import Any, Dict
from ..base import BaseTool
from ..mcp_manager import MCPServerManager

class MCPTool(BaseTool):
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.manager = MCPServerManager()
        self.tool_name = config.get("tool_name")
        if not self.tool_name:
            raise ValueError("MCPTool config must specify 'tool_name'")

    def execute(self, input: Any) -> Any:
        # Input is usually a dictionary of arguments for the tool
        # If input is a string, we might need to map it to the expected argument
        arguments = input
        if isinstance(input, str):
            # If there's only one argument expected, we might guess, 
            # but usually MCP tools define schemas.
            # For now, if string, wrap in a default 'query' or similar if configured,
            # or pass as is if the tool expects a single string arg (less common in MCP).
            # A safe fallback is to check config for a mapping.
            arg_key = self.config.get("default_arg_key", "input")
            arguments = {arg_key: input}
        
        return self.manager.call_tool(self.config, self.tool_name, arguments)

    @property
    def description(self) -> str:
        # Optionally, we could fetch the description from the server dynamically
        # But for now, rely on the config description
        return super().description
