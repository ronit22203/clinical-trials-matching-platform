from pathlib import Path

import numpy as np

from src.storage.embedder import MedicalVectorizer, _canonical_source_name, _chunk_sha256


def test_canonical_source_maps_hash_filename_to_doi_cleaned_name() -> None:
    file_path = Path("812d93d6a62ca8cfbfc5bca9cdcb8874a2042c197d8482641103dd34057672cc.md")
    text = "medRxiv preprint doi: https://doi.org/10.1101/2026.03.17.26348414"
    assert _canonical_source_name(file_path, text) == "2026.03.17.26348414_cleaned.md"


def test_chunk_sha256_is_stable_for_same_content() -> None:
    content = "Same chunk content"
    assert _chunk_sha256(content) == _chunk_sha256(content)


def test_process_file_skips_duplicate_chunk_content(tmp_path) -> None:
    class DummyCleaner:
        def clean(self, text: str) -> str:
            return text

    class DummyChunker:
        def chunk(self, text: str):
            return [
                {"content": "duplicate chunk", "context": "A", "level": 1, "page_number": 1, "is_boilerplate": False},
                {"content": "duplicate chunk", "context": "A", "level": 1, "page_number": 1, "is_boilerplate": False},
            ]

    class DummyEmbedder:
        def encode(self, text: str, normalize_embeddings: bool = False):
            return np.array([0.1, 0.2, 0.3], dtype=float)

    class DummyClient:
        def __init__(self):
            self.upserts = []

        def upsert(self, collection_name, points):
            self.upserts.append((collection_name, points))

    sample_file = tmp_path / "812d93d6a62ca8cfbfc5bca9cdcb8874a2042c197d8482641103dd34057672cc.md"
    sample_file.write_text("doi: 10.1101/2026.03.17.26348414", encoding="utf-8")

    vectorizer = MedicalVectorizer.__new__(MedicalVectorizer)
    vectorizer.config = {"vectorization": {"batch_size": 64}, "chunking": {"filter_boilerplate": True}}
    vectorizer.collection_name = "test_collection"
    vectorizer.cleaner = DummyCleaner()
    vectorizer.chunker = DummyChunker()
    vectorizer.embedding_model = DummyEmbedder()
    vectorizer._normalize_embeddings = False
    vectorizer.client = DummyClient()

    vectorizer.process_file(str(sample_file))

    assert len(vectorizer.client.upserts) == 1
    _, points = vectorizer.client.upserts[0]
    assert len(points) == 1
    assert points[0].payload["source"] == "2026.03.17.26348414_cleaned.md"
    assert points[0].payload["content_sha256"] == _chunk_sha256("duplicate chunk")
