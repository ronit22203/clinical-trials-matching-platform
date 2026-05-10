"""
Unit tests for the GraphRAG tool.

Qdrant, Neo4j, and SentenceTransformer are mocked so tests run offline.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.tools.graphrag import GraphRAGTool, _extract_keywords


# ---------------------------------------------------------------------------
# Config fixture
# ---------------------------------------------------------------------------

BASE_CONFIG = {
    "qdrant_url": "http://localhost:6333",
    "collection": "test",
    "embedding_model": "BAAI/bge-small-en-v1.5",
    "model_cache_dir": "data/models",
    "neo4j_uri": "bolt://localhost:7687",
    "neo4j_username": "neo4j",
    "neo4j_password": "password",
    "limit": 2,
    "neo4j_limit": 5,
    "reranker_model": None,
    "cache_ttl": 60,
    "cache_maxsize": 32,
}


# ---------------------------------------------------------------------------
# _extract_keywords
# ---------------------------------------------------------------------------

class TestExtractKeywords:
    def test_filters_stop_words(self):
        keywords = _extract_keywords("what are the side effects of metformin")
        assert "what" not in keywords
        assert "are" not in keywords
        assert "the" not in keywords

    def test_extracts_meaningful_words(self):
        keywords = _extract_keywords("GLP-1 agonists in type 2 diabetes management")
        # Should contain substantive terms
        assert len(keywords) > 0

    def test_max_keywords_respected(self):
        text = "alpha beta gamma delta epsilon zeta eta theta iota kappa"
        keywords = _extract_keywords(text, max_keywords=3)
        assert len(keywords) <= 3

    def test_empty_query(self):
        assert _extract_keywords("") == []

    def test_short_words_filtered(self):
        keywords = _extract_keywords("is it ok to use it")
        # All words <= 2 chars should be excluded
        assert all(len(k) > 2 for k in keywords)


# ---------------------------------------------------------------------------
# GraphRAGTool.execute — mocked clients
# ---------------------------------------------------------------------------

class TestGraphRAGToolExecute:
    def _make_tool(self, config: dict | None = None) -> GraphRAGTool:
        return GraphRAGTool(config or BASE_CONFIG)

    def test_returns_found_true_on_vector_hits(self):
        tool = self._make_tool()
        mock_vector_results = [
            {
                "score": 0.8,
                "content": "Metformin reduces HbA1c.",
                "source": "doc.pdf",
                "chunk_id": "c1",
                "chunk_index": 0,
                "context": None,
            }
        ]
        with patch.object(tool, "_vector_search", return_value=mock_vector_results), \
             patch.object(tool, "_graph_context", return_value=[]):
            result = tool.execute("metformin diabetes")

        assert result["found"] is True
        assert len(result["vector_results"]) == 1
        assert result["vector_results"][0]["content"] == "Metformin reduces HbA1c."

    def test_returns_found_false_on_empty_results(self):
        tool = self._make_tool()
        with patch.object(tool, "_vector_search", return_value=[]), \
             patch.object(tool, "_graph_context", return_value=[]):
            result = tool.execute("completely unknown term xyz")

        assert result["found"] is False
        assert result["vector_results"] == []

    def test_graph_facts_included(self):
        tool = self._make_tool()
        mock_vector_results = [
            {"score": 0.7, "content": "Some content.", "source": "doc.pdf",
             "chunk_id": "c1", "chunk_index": 0, "context": None}
        ]
        graph_facts = ["DrugA --[TREATS]--> DiseaseB"]
        with patch.object(tool, "_vector_search", return_value=mock_vector_results), \
             patch.object(tool, "_graph_context", return_value=graph_facts):
            result = tool.execute("DrugA treatment")

        assert result["graph_facts"] == graph_facts

    def test_empty_query_returns_error(self):
        tool = self._make_tool()
        result = tool.execute("")
        assert "Error" in str(result)

    def test_vector_search_failure_returns_error(self):
        tool = self._make_tool()
        mock_client = MagicMock()
        mock_client.query_points.side_effect = ConnectionError("Qdrant unavailable")

        mock_embedder = MagicMock()
        mock_embedder.encode.return_value = [0.0] * 384

        tool._qdrant = mock_client
        tool._embedder = mock_embedder

        result = tool.execute("some query")
        assert "Error" in str(result)


# ---------------------------------------------------------------------------
# TTL cache (BaseTool.cached_execute)
# ---------------------------------------------------------------------------

class TestCaching:
    def test_cache_prevents_double_execution(self):
        tool = GraphRAGTool(BASE_CONFIG)
        call_count = 0

        def fake_execute(query):
            nonlocal call_count
            call_count += 1
            return {"found": True, "vector_results": [], "graph_facts": []}

        tool.execute = fake_execute  # type: ignore[method-assign]
        tool.cached_execute("same query")
        tool.cached_execute("same query")
        assert call_count == 1

    def test_different_queries_execute_separately(self):
        tool = GraphRAGTool(BASE_CONFIG)
        call_count = 0

        def fake_execute(query):
            nonlocal call_count
            call_count += 1
            return {"found": False, "vector_results": [], "graph_facts": []}

        tool.execute = fake_execute  # type: ignore[method-assign]
        tool.cached_execute("query A")
        tool.cached_execute("query B")
        assert call_count == 2
