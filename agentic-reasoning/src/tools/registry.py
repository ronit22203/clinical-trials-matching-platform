from __future__ import annotations

import importlib
from typing import Any

from ..config_loader import load_app_config
from ..schemas.tool import ToolConfig
from .base import BaseTool


class ToolRegistry:
    def __init__(self, tool_configs: dict[str, dict[str, Any]] | None = None):
        self._tool_configs = tool_configs or {}
        self._tools: dict[str, BaseTool] = {}
        self._load_all()

    @classmethod
    def from_app_config(cls, only: list[str] | None = None) -> "ToolRegistry":
        app_config = load_app_config()
        tools = app_config.get("agentic_reasoning", {}).get("tools", {})
        if only is not None:
            only_set = set(only)
            tools = {name: cfg for name, cfg in tools.items() if name in only_set}
        return cls(tool_configs=tools)

    @classmethod
    def from_agent_config(cls, agent_config) -> "ToolRegistry":
        only = [tool.name for tool in getattr(agent_config, "tools", [])]
        return cls.from_app_config(only=only)

    def _load_all(self) -> None:
        for tool_name, data in self._tool_configs.items():
            payload = dict(data)
            payload.setdefault("name", tool_name)
            self._load_tool(payload)

    def _load_tool(self, data: dict[str, Any]) -> None:
        try:
            tool_config = ToolConfig(**data)
            if not tool_config.enabled:
                return
            module = importlib.import_module(tool_config.module)
            tool_class = getattr(module, tool_config.class_name)
            instance = tool_class(tool_config.config)
            self._tools[tool_config.name] = instance
            print(f"Loaded tool: {tool_config.name}")
        except Exception as e:
            print(f"Failed to load tool from {data.get('name', 'unknown')}: {e}")

    def get_tool(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())
