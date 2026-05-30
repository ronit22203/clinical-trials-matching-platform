import logging

from benchmarking.evaluators.retrieval_evaluator import RetrievalEvaluator, _recall_at_k


def test_recall_is_clamped_to_one() -> None:
    assert _recall_at_k([1, 1, 1], k=3, total_relevant=2) == 1.0


def test_duplicate_retrievals_are_deduplicated_and_warned(caplog) -> None:
    class FakeEvaluator(RetrievalEvaluator):
        def _query(self, text: str):
            return [
                {
                    "rank": 1,
                    "chunk_index": 0,
                    "score": 0.95,
                    "source": "812d93...hash.md",
                    "canonical_source": "2026.03.17.26348414_cleaned.md",
                    "content_sha256": "abc123",
                    "page_number": 1,
                    "content_preview": "duplicate chunk",
                },
                {
                    "rank": 2,
                    "chunk_index": 0,
                    "score": 0.94,
                    "source": "2026.03.17.26348414_cleaned.md",
                    "canonical_source": "2026.03.17.26348414_cleaned.md",
                    "content_sha256": "abc123",
                    "page_number": 1,
                    "content_preview": "duplicate chunk",
                },
                {
                    "rank": 3,
                    "chunk_index": 1,
                    "score": 0.90,
                    "source": "2026.03.17.26348414_cleaned.md",
                    "canonical_source": "2026.03.17.26348414_cleaned.md",
                    "content_sha256": "def456",
                    "page_number": 2,
                    "content_preview": "another relevant chunk",
                },
            ]

    evaluator = FakeEvaluator(
        qdrant_url="http://localhost:6333",
        collection="medical_papers",
        embedding_model="BAAI/bge-small-en-v1.5",
        top_k=5,
    )
    query = {
        "id": "q1",
        "text": "test query",
        "relevance_grades": {"chunk_00": 1, "chunk_01": 1},
    }

    with caplog.at_level(logging.WARNING):
        result = evaluator.evaluate_query(query)

    assert result["recall_at_5"] == 1.0
    assert len(result["retrieved_chunks"]) == 2
    assert any("Duplicate retrieved sources detected" in r.message for r in caplog.records)
