import asyncio
import threading
from typing import Dict, Optional, Any
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from contextlib import AsyncExitStack

class MCPServerManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(MCPServerManager, cls).__new__(cls)
                cls._instance.initialized = False
        return cls._instance

    def __init__(self):
        if self.initialized:
            return
        self.initialized = True
        self._servers: Dict[str, Any] = {}  # Map config_hash -> (session, exit_stack)
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _get_config_hash(self, config: dict) -> str:
        # Simple hash based on command and args to identify unique servers
        server_config = config.get("server", {})
        cmd = server_config.get("command", "")
        args = tuple(server_config.get("args", []))
        env = tuple(sorted(server_config.get("env", {}).items()))
        return f"{cmd}|{args}|{env}"

    async def _connect(self, config: dict):
        config_hash = self._get_config_hash(config)
        if config_hash in self._servers:
            return self._servers[config_hash][0]

        server_config = config.get("server", {})
        command = server_config.get("command")
        args = server_config.get("args", [])
        env = server_config.get("env", None)

        server_params = StdioServerParameters(
            command=command,
            args=args,
            env=env
        )

        exit_stack = AsyncExitStack()
        # stdio_client returns (read, write)
        read, write = await exit_stack.enter_async_context(stdio_client(server_params))
        
        # ClientSession also needs to be entered
        session = await exit_stack.enter_async_context(ClientSession(read, write))
        
        await session.initialize()
        
        self._servers[config_hash] = (session, exit_stack)
        return session

    def call_tool(self, config: dict, tool_name: str, arguments: dict) -> Any:
        future = asyncio.run_coroutine_threadsafe(
            self._call_tool_async(config, tool_name, arguments),
            self._loop
        )
        return future.result()

    async def _call_tool_async(self, config: dict, tool_name: str, arguments: dict) -> Any:
        try:
            session = await self._connect(config)
            result = await session.call_tool(tool_name, arguments)
            return result
        except Exception as e:
            return f"Error calling MCP tool {tool_name}: {str(e)}"

    def list_tools(self, config: dict):
        future = asyncio.run_coroutine_threadsafe(
            self._list_tools_async(config),
            self._loop
        )
        return future.result()
    
    async def _list_tools_async(self, config: dict):
        try:
            session = await self._connect(config)
            result = await session.list_tools()
            return result
        except Exception as e:
            return f"Error listing tools: {str(e)}"
