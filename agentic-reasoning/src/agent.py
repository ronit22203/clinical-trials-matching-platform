# src/agent.py
import asyncio
import time
from typing import Iterator
from langchain_core.messages import AIMessageChunk, HumanMessage, SystemMessage
from langchain_core.tools import tool as lc_tool
from langgraph.prebuilt import create_react_agent
from .config_loader import AgentConfig
from .llm_factory import build_llm


class ExecutionMetrics:
    """Captures execution metrics for logging."""
    def __init__(self, config: AgentConfig):
        self.model = config.model
        self.temperature = config.model_params.temperature
        self.top_p = config.model_params.top_p
        self.system_instruction = config.system_prompt or ""
        self.tools_called = []
        self.tool_responses: dict = {}
        self.start_time = None
        self.end_time = None
        self.tokens_input = 0
        self.tokens_output = 0
        self.response = ""

    @property
    def latency_ms(self) -> float:
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time) * 1000
        return 0.0


class SimpleAgent:
    def __init__(self, config: AgentConfig, tool_registry=None):
        self.config = config
        params = config.model_params.model_dump()
        self.llm = build_llm(config.model, **params)
        self.tool_registry = tool_registry
        self.metrics = None

        self._agent = None
        if tool_registry and config.tools:
            lc_tools = self._build_langchain_tools(config, tool_registry)
            if lc_tools:
                prompt = config.system_prompt or "You are a helpful clinical research assistant."
                self._agent = create_react_agent(self.llm, lc_tools, prompt=prompt)

    def _build_langchain_tools(self, config, tool_registry):
        tools = []
        for tool_cfg in config.tools:
            instance = tool_registry.get_tool(tool_cfg.name)
            if instance:
                description = instance.description
                name = tool_cfg.name

                @lc_tool(name, description=description)
                def _tool(input: str, _fn=instance.cached_execute, _name=name) -> str:
                    result = str(_fn(input))
                    if self.metrics:
                        if _name not in self.metrics.tools_called:
                            self.metrics.tools_called.append(_name)
                        self.metrics.tool_responses[_name] = result
                    return result

                tools.append(_tool)
        return tools

    def run(self, query: str) -> str:
        self.metrics = ExecutionMetrics(self.config)
        self.metrics.start_time = time.time()

        try:
            if self._agent:
                result = self._agent.invoke({"messages": [HumanMessage(content=query)]})
                response = result["messages"][-1].content
            else:
                messages = []
                if self.config.system_prompt:
                    messages.append(SystemMessage(content=self.config.system_prompt))
                messages.append(HumanMessage(content=query))
                response = self.llm.invoke(messages).content

            self.metrics.response = response

            try:
                self.metrics.tokens_input = self.llm.get_num_tokens(query)
                self.metrics.tokens_output = self.llm.get_num_tokens(response)
            except Exception:
                pass

            return response
        finally:
            self.metrics.end_time = time.time()

    def stream(self, query: str) -> Iterator[str]:
        """Yield response tokens as they are generated.

        For the no-tool path, streams directly from the LLM.
        For the ReAct path, streams events and yields only AI content chunks.
        Populates self.metrics on completion.
        """
        self.metrics = ExecutionMetrics(self.config)
        self.metrics.start_time = time.time()
        response_parts: list[str] = []

        try:
            if self._agent:
                for event in self._agent.stream(
                    {"messages": [HumanMessage(content=query)]},
                    stream_mode="messages",
                ):
                    # stream_mode="messages" yields (message_chunk, metadata) tuples.
                    # Only yield content from AI response chunks — ToolMessages and
                    # HumanMessages must be suppressed so raw JSON tool payloads don't
                    # appear in the terminal output.
                    chunk, meta = event if isinstance(event, tuple) else (event, {})
                    if not isinstance(chunk, AIMessageChunk):
                        # Still track tool calls from ToolMessage metadata
                        if self.metrics and meta.get("langgraph_node") == "tools":
                            tool_name = getattr(chunk, "name", None)
                            if tool_name and tool_name not in self.metrics.tools_called:
                                self.metrics.tools_called.append(tool_name)
                        continue
                    token = chunk.content or ""
                    if token:
                        response_parts.append(token)
                        yield token
            else:
                messages = []
                if self.config.system_prompt:
                    messages.append(SystemMessage(content=self.config.system_prompt))
                messages.append(HumanMessage(content=query))
                for chunk in self.llm.stream(messages):
                    token = chunk.content or ""
                    if token:
                        response_parts.append(token)
                        yield token
        finally:
            self.metrics.end_time = time.time()
            self.metrics.response = "".join(response_parts)
            try:
                self.metrics.tokens_input = self.llm.get_num_tokens(query)
                self.metrics.tokens_output = self.llm.get_num_tokens(self.metrics.response)
            except Exception:
                pass

    def run_parallel(self, query: str) -> str:
        """Fan out all configured tool calls concurrently, then synthesize with the LLM.

        Bypasses the LangGraph ReAct loop — all tools run at once via asyncio.gather
        (each sync execute() is offloaded to a thread). Suitable when every configured
        tool is relevant to the query, mirroring ClinicalResearchWorkflow without Temporal.
        Falls back to run() if no tools are configured.
        """
        if not self.tool_registry or not self.config.tools:
            return self.run(query)

        self.metrics = ExecutionMetrics(self.config)
        self.metrics.start_time = time.time()

        async def _gather() -> dict[str, str]:
            async def _call(name: str, instance) -> tuple[str, str]:
                result = await asyncio.to_thread(instance.cached_execute, query)
                return name, str(result)

            tasks = [
                _call(tc.name, self.tool_registry.get_tool(tc.name))
                for tc in self.config.tools
                if self.tool_registry.get_tool(tc.name)
            ]
            return dict(await asyncio.gather(*tasks))

        tool_results = asyncio.run(_gather())
        self.metrics.tools_called = list(tool_results.keys())
        self.metrics.tool_responses = tool_results

        context = "\n\n".join(
            f"[{name}]\n{result}" for name, result in tool_results.items()
        )
        system = self.config.system_prompt or "You are a helpful clinical research assistant."
        synthesis_prompt = (
            f"{system}\n\nUse the following tool results to answer the user's query.\n\n"
            f"{context}"
        )
        messages = [
            SystemMessage(content=synthesis_prompt),
            HumanMessage(content=query),
        ]
        try:
            response = self.llm.invoke(messages).content
            self.metrics.response = response
            try:
                self.metrics.tokens_input = self.llm.get_num_tokens(query)
                self.metrics.tokens_output = self.llm.get_num_tokens(response)
            except Exception:
                pass
            return response
        finally:
            self.metrics.end_time = time.time()