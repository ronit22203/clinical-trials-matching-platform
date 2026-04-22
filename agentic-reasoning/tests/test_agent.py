"""Tests for the SimpleAgent."""
from unittest.mock import MagicMock, patch
import pytest

from src.config_loader import AgentConfig, ModelParams
from src.agent import SimpleAgent


def _make_config(with_tools=False, provider="ollama"):
    tools = [MagicMock(name="fda_adverse_events")] if with_tools else []
    return AgentConfig(
        name="Test Agent",
        model=f"{provider}/test-model",
        system_prompt="You are a test assistant.",
        model_params=ModelParams(),
        tools=tools,
    )


class TestSimpleAgentNoTools:
    @patch("src.agent.build_llm")
    def test_run_returns_llm_content(self, mock_build_llm):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="Hello!")
        mock_build_llm.return_value = mock_llm

        agent = SimpleAgent(_make_config())
        result = agent.run("Hi")
        assert result == "Hello!"
        mock_llm.invoke.assert_called_once()

    @patch("src.agent.build_llm")
    def test_system_prompt_included_in_messages(self, mock_build_llm):
        from langchain_core.messages import SystemMessage, HumanMessage
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="ok")
        mock_build_llm.return_value = mock_llm

        agent = SimpleAgent(_make_config())
        agent.run("test query")

        call_args = mock_llm.invoke.call_args[0][0]
        assert any(isinstance(m, SystemMessage) for m in call_args)
        assert any(isinstance(m, HumanMessage) for m in call_args)

    @patch("src.agent.build_llm")
    def test_sglang_provider_model_config(self, mock_build_llm):
        """build_llm is called with the full model string including provider prefix."""
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="ok")
        mock_build_llm.return_value = mock_llm

        config = _make_config(provider="sglang")
        SimpleAgent(config)
        call_kwargs = mock_build_llm.call_args
        assert call_kwargs[0][0] == "sglang/test-model"
