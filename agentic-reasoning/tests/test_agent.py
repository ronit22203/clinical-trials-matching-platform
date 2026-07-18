"""
Tests for the two-phase Agent pipeline.

GraphRAG is mocked so these tests run without Qdrant/Neo4j/LLM.
The key invariant: Phase 1 (GraphRAG) is ALWAYS called before the LLM.
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock


from src.agent import Agent, _format_evidence, _NO_EVIDENCE_RESPONSE
from src.config import AgentConfig, GraphRAGConfig, ModelParams


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

EVIDENCE_WITH_RESULTS: dict[str, Any] = {
    "found": True,
    "source": "graphrag",
    "query": "GLP-1 agonists",
    "keywords": ["GLP-1", "agonists"],
    "vector_results": [
        {
            "score": 0.87,
            "content": "GLP-1 receptor agonists reduce HbA1c by ~1.5%.",
            "source": "paper_001.pdf",
            "chunk_id": "chunk_1",
            "chunk_index": 0,
        }
    ],
    "graph_facts": ["GLP-1 --[TREATS]--> Type2Diabetes"],
}

EVIDENCE_NO_RESULTS: dict[str, Any] = {
    "found": False,
    "source": "graphrag",
    "query": "unknown drug",
    "keywords": [],
    "vector_results": [],
    "graph_facts": [],
}


def _make_agent(evidence: dict[str, Any]) -> Agent:
    """Create an Agent with GraphRAG and LLM mocked."""
    config = AgentConfig(
        model="lmstudio/test-model",
        system_prompt="Test system prompt.",
        model_params=ModelParams(temperature=0.1, max_tokens=256),
        graphrag=GraphRAGConfig(
            qdrant_url="http://localhost:6333",
            collection="test",
            embedding_model="test-embed",
            neo4j_uri="bolt://localhost:7687",
            neo4j_username="neo4j",
            neo4j_password="password",
        ),
    )
    agent = Agent.__new__(Agent)
    agent.config = config

    # Mock GraphRAG
    mock_graphrag = MagicMock()
    mock_graphrag.cached_execute.return_value = evidence
    agent.graphrag = mock_graphrag

    # Mock LLM
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "Synthesized answer from evidence."
    mock_llm.invoke.return_value = mock_response
    mock_llm.stream.return_value = iter([mock_response])
    agent.llm = mock_llm

    return agent


# ---------------------------------------------------------------------------
# Phase 1: GraphRAG always called
# ---------------------------------------------------------------------------

class TestPhase1Enforcement:
    def test_graphrag_called_on_run(self):
        agent = _make_agent(EVIDENCE_WITH_RESULTS)
        agent.run("test query")
        agent.graphrag.cached_execute.assert_called_once_with("test query")

    def test_graphrag_called_on_stream(self):
        agent = _make_agent(EVIDENCE_WITH_RESULTS)
        list(agent.stream("test query"))
        agent.graphrag.cached_execute.assert_called_once_with("test query")

    def test_graphrag_called_before_llm(self):
        """Verify GraphRAG executes and LLM is invoked after — call order check."""
        call_order = []
        agent = _make_agent(EVIDENCE_WITH_RESULTS)
        agent.graphrag.cached_execute.side_effect = lambda q: (call_order.append("graphrag"), EVIDENCE_WITH_RESULTS)[1]
        agent.llm.invoke.side_effect = lambda msgs: (call_order.append("llm"), MagicMock(content="ok"))[1]

        agent.run("query")
        assert call_order == ["graphrag", "llm"], f"Expected graphrag → llm, got {call_order}"


# ---------------------------------------------------------------------------
# Phase 2: Grounded synthesis
# ---------------------------------------------------------------------------

class TestPhase2Synthesis:
    def test_synthesis_contains_evidence_context(self):
        """The messages sent to the LLM must include evidence content."""
        agent = _make_agent(EVIDENCE_WITH_RESULTS)
        captured_messages = []

        def capture_invoke(messages):
            captured_messages.extend(messages)
            return MagicMock(content="answer")

        agent.llm.invoke.side_effect = capture_invoke
        agent.run("GLP-1 agonists")

        human_content = captured_messages[-1].content
        assert "[EVIDENCE]" in human_content
        assert "GLP-1 receptor agonists" in human_content

    def test_llm_not_called_when_no_evidence(self):
        """When GraphRAG returns found=False, the LLM must NOT be invoked."""
        agent = _make_agent(EVIDENCE_NO_RESULTS)
        result = agent.run("unknown drug")
        agent.llm.invoke.assert_not_called()
        assert result.synthesis == _NO_EVIDENCE_RESPONSE

    def test_no_evidence_stream(self):
        agent = _make_agent(EVIDENCE_NO_RESULTS)
        tokens = list(agent.stream("unknown drug"))
        agent.llm.stream.assert_not_called()
        assert "".join(tokens) == _NO_EVIDENCE_RESPONSE


# ---------------------------------------------------------------------------
# RunResult
# ---------------------------------------------------------------------------

class TestRunResult:
    def test_found_flag_reflects_evidence(self):
        agent = _make_agent(EVIDENCE_WITH_RESULTS)
        result = agent.run("query")
        assert result.found is True

    def test_not_found_flag(self):
        agent = _make_agent(EVIDENCE_NO_RESULTS)
        result = agent.run("query")
        assert result.found is False

    def test_latency_ms_positive(self):
        agent = _make_agent(EVIDENCE_WITH_RESULTS)
        result = agent.run("query")
        assert result.latency_ms > 0

    def test_run_json_serialisable(self):
        agent = _make_agent(EVIDENCE_WITH_RESULTS)
        data = agent.run_json("query")
        json.dumps(data)  # must not raise
        assert "synthesis" in data
        assert "evidence" in data
        assert "found" in data


# ---------------------------------------------------------------------------
# _format_evidence helper
# ---------------------------------------------------------------------------

class TestFormatEvidence:
    def test_formats_vector_results(self):
        text = _format_evidence(EVIDENCE_WITH_RESULTS)
        assert "paper_001.pdf" in text
        assert "GLP-1 receptor agonists" in text

    def test_formats_graph_facts(self):
        text = _format_evidence(EVIDENCE_WITH_RESULTS)
        assert "GLP-1 --[TREATS]--> Type2Diabetes" in text

    def test_empty_evidence_returns_no_evidence_string(self):
        text = _format_evidence(EVIDENCE_NO_RESULTS)
        assert "No evidence" in text
