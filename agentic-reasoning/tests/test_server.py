"""FastAPI contract tests for synthesis availability and fallback metadata."""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
import pytest

from src.agent import LLMUnavailableError, SynthesisResult
from src import server


EVIDENCE: dict[str, Any] = {
    "found": True,
    "vector_results": [
        {
            "score": 0.82,
            "reranker_score": 0.01,
            "content": "Evidence content.",
            "source": "paper.pdf",
            "chunk_index": 2,
            "context": "Guideline",
        }
    ],
    "graph_facts": ["DRUG --[TREATS]--> CONDITION"],
    "graph_anchor": "DRUG",
}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    agent = MagicMock()
    agent.graphrag.cached_execute.return_value = EVIDENCE

    async def get_agent() -> MagicMock:
        return agent

    monkeypatch.setattr(server, "_get_agent", get_agent)
    server._evidence_cache.clear()
    return TestClient(server.app)


def test_match_uses_vector_relevance_not_raw_reranker_score(client: TestClient) -> None:
    response = client.post("/api/match", data={"query": "clinical query"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["matches"][0]["score"] == 0.82
    assert payload["matches"][0]["rankScore"] == 0.01
    assert payload["graphAnchor"] == "DRUG"


def test_synthesis_returns_fallback_metadata(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = MagicMock()
    agent.graphrag.cached_execute.return_value = EVIDENCE
    agent.synthesize.return_value = SynthesisResult(
        text="Grounded fallback synthesis.",
        model="lmstudio/fallback-model",
        fallback_used=True,
    )

    async def get_agent() -> MagicMock:
        return agent

    monkeypatch.setattr(server, "_get_agent", get_agent)
    response = client.post(
        "/api/synthesis",
        json={"query": "clinical query", "evidence": []},
    )

    assert response.status_code == 200
    assert response.json() == {
        "synthesis": "Grounded fallback synthesis.",
        "model": "lmstudio/fallback-model",
        "fallbackUsed": True,
        "tokensUsed": None,
    }


def test_synthesis_returns_retryable_503_when_no_provider_is_available(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = MagicMock()
    agent.graphrag.cached_execute.return_value = EVIDENCE
    agent.synthesize.side_effect = LLMUnavailableError("primary and fallback unavailable")

    async def get_agent() -> MagicMock:
        return agent

    monkeypatch.setattr(server, "_get_agent", get_agent)
    response = client.post(
        "/api/synthesis",
        json={"query": "clinical query", "evidence": []},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "synthesis_unavailable",
        "message": "primary and fallback unavailable",
        "retryable": True,
    }
