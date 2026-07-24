"""Unit tests for scoped, idempotent Stage 5 indexing."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest

from src.storage import embedder


class FakeQdrantClient:
    """In-memory Qdrant call recorder; no service is required."""

    def __init__(self, *, url: str) -> None:
        self.url = url
        self.collections: set[str] = set()
        self.created: list[tuple[str, Any]] = []
        self.deleted: list[tuple[str, Any]] = []
        self.upserts: list[tuple[str, list[Any]]] = []

    def collection_exists(self, collection_name: str) -> bool:
        return collection_name in self.collections

    def create_collection(self, *, collection_name: str, vectors_config: Any) -> None:
        self.collections.add(collection_name)
        self.created.append((collection_name, vectors_config))

    def delete(self, *, collection_name: str, points_selector: Any) -> None:
        self.deleted.append((collection_name, points_selector))

    def upsert(self, *, collection_name: str, points: list[Any]) -> None:
        self.upserts.append((collection_name, points))


class FakeEmbeddingModel:
    """Deterministic model substitute; no model download is required."""

    def __init__(self, model_name: str, *, device: str) -> None:
        self.model_name = model_name
        self.device = device
        self.encoded: list[list[str]] = []

    def get_sentence_embedding_dimension(self) -> int:
        return 3

    def encode(
        self, contents: list[str], *, normalize_embeddings: bool
    ) -> list[list[float]]:
        self.encoded.append(contents)
        return [[float(index), 0.0, 1.0] for index, _ in enumerate(contents)]


@pytest.fixture
def vectorizer(monkeypatch: pytest.MonkeyPatch) -> embedder.MedicalVectorizer:
    """Construct a vectorizer with all external dependencies mocked."""
    monkeypatch.setattr(embedder, "QdrantClient", FakeQdrantClient)
    monkeypatch.setattr(embedder, "SentenceTransformer", FakeEmbeddingModel)
    return embedder.MedicalVectorizer(
        config={
            "vectorization": {
                "qdrant_url": "http://qdrant.invalid",
                "model_name": "test-model",
                "device": "cpu",
                "batch_size": 1,
                "distance_metric": "cosine",
            },
            "chunking": {"filter_boilerplate": True},
        }
    )


def test_index_chunks_path_replaces_only_matching_scoped_document(
    vectorizer: embedder.MedicalVectorizer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Patient points are deterministic and deleted by source plus scope first."""
    artifact = {
        "filename": "uploaded_record",
        "source_file": "uploaded_record_cleaned.md",
        "chunks": [
            {
                "content": "Clinical note summary",
                "context": "Assessment",
                "level": 2,
                "page_number": 3,
            },
            {
                "content": "Footer",
                "context": "",
                "level": 0,
                "is_boilerplate": True,
            },
        ],
    }
    monkeypatch.setattr(
        vectorizer,
        "_load_chunks",
        lambda _: (artifact, artifact["chunks"]),
    )

    first_count = vectorizer.index_chunks_path(
        Path("uploaded_record_chunks.json"),
        scope="patient_context",
        collection_name="patient_context",
    )
    second_count = vectorizer.index_chunks_path(
        Path("uploaded_record_chunks.json"),
        scope="patient_context",
        collection_name="patient_context",
    )

    client = vectorizer.client
    assert isinstance(client, FakeQdrantClient)
    assert first_count == second_count == 1
    assert [name for name, _ in client.created] == ["patient_context"]
    assert [name for name, _ in client.deleted] == [
        "patient_context",
        "patient_context",
    ]

    point_filter = client.deleted[0][1].filter
    assert {
        condition.key: condition.match.value for condition in point_filter.must
    } == {"source": "uploaded_record.pdf", "scope": "patient_context"}

    first_point = client.upserts[0][1][0]
    second_point = client.upserts[1][1][0]
    assert first_point.id == second_point.id
    assert first_point.id == str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            "patient_context:patient_context:uploaded_record.pdf:0",
        )
    )
    assert first_point.payload == {
        "source": "uploaded_record.pdf",
        "scope": "patient_context",
        "content": "Clinical note summary",
        "context": "Assessment",
        "level": 2,
        "chunk_index": 0,
        "page_number": 3,
    }


def test_index_chunks_path_requires_explicit_scope_and_collection(
    vectorizer: embedder.MedicalVectorizer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Blank routing metadata is rejected before a collection can be selected."""
    monkeypatch.setattr(vectorizer, "_load_chunks", lambda _: ({}, []))

    with pytest.raises(ValueError, match="scope is required"):
        vectorizer.index_chunks_path(
            "document_chunks.json", scope="", collection_name="medical_papers"
        )

    with pytest.raises(ValueError, match="collection_name is required"):
        vectorizer.index_chunks_path(
            "document_chunks.json", scope="literature", collection_name=""
        )
