"""Stage 5 vector indexing for persisted Stage 4 chunk artifacts."""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchValue,
    PointStruct,
    VectorParams,
)

from src.config_loader import load_ingestion_config

try:
    from sentence_transformers import SentenceTransformer
except ImportError as exc:
    raise ImportError(
        "Please install sentence-transformers: pip install sentence-transformers"
    ) from exc


log = logging.getLogger(__name__)
_POINT_ID_NAMESPACE = uuid.NAMESPACE_URL


class ConfigLoader:
    """Load ingestion configuration from YAML."""

    @staticmethod
    def load(config_path: str | None = None) -> Dict[str, Any]:
        """Load the configured ingestion policy."""
        return load_ingestion_config(config_path)


class MedicalVectorizer:
    """Embed persisted chunk artifacts into an explicitly selected Qdrant collection."""

    def __init__(
        self,
        config: Dict[str, Any] | None = None,
        collection_name: str | None = None,
    ) -> None:
        """Create Qdrant and embedding-model clients without indexing any documents."""
        self.config = config if config is not None else ConfigLoader.load()
        vec_config = self.config.get("vectorization", {})
        self.collection_name = collection_name or vec_config.get(
            "collection_name", "medical_papers"
        )
        self._batch_size = int(vec_config.get("batch_size", 64))
        self._normalize_embeddings = bool(vec_config.get("normalize_embeddings", False))

        qdrant_url = vec_config.get("qdrant_url", "http://localhost:6333")
        log.info("Connecting vectorizer to Qdrant")
        self.client = QdrantClient(url=qdrant_url)

        model_name = vec_config.get("model_name", "BAAI/bge-small-en-v1.5")
        device = vec_config.get("device", "cpu")
        log.info("Loading embedding model name=%s device=%s", model_name, device)
        self.embedding_model = SentenceTransformer(model_name, device=device)
        self.embedding_dim = self.embedding_model.get_sentence_embedding_dimension()

        metric_name = str(vec_config.get("distance_metric", "cosine")).lower()
        self._distance = {
            "cosine": Distance.COSINE,
            "dot": Distance.DOT,
            "euclidean": Distance.EUCLID,
        }.get(metric_name, Distance.COSINE)
        self._distance_name = metric_name

    def _ensure_collection(self, collection_name: str) -> None:
        """Create *collection_name* when it does not yet exist."""
        if self.client.collection_exists(collection_name):
            return

        log.info(
            "Creating vector collection name=%s dimensions=%s distance=%s",
            collection_name,
            self.embedding_dim,
            self._distance_name,
        )
        self.client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=self.embedding_dim, distance=self._distance),
        )

    @staticmethod
    def _source_from_artifact(artifact: Dict[str, Any], chunks_path: Path) -> str:
        """Derive stable PDF provenance from a Stage 4 artifact."""
        explicit_source = artifact.get("source")
        if isinstance(explicit_source, str) and explicit_source.strip():
            return explicit_source

        source_file = artifact.get("source_file")
        filename = artifact.get("filename")
        candidate = source_file if isinstance(source_file, str) else filename
        if not isinstance(candidate, str) or not candidate.strip():
            candidate = chunks_path.stem.removesuffix("_chunks")

        candidate_path = Path(candidate)
        stem = candidate_path.stem.removesuffix("_cleaned")
        return f"{stem}.pdf"

    @staticmethod
    def _load_chunks(chunks_path: Path) -> tuple[Dict[str, Any], list[Dict[str, Any]]]:
        """Load and validate a persisted Stage 4 chunks JSON artifact."""
        try:
            raw_artifact = json.loads(chunks_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Invalid chunks artifact: {chunks_path.name}") from exc

        if not isinstance(raw_artifact, dict):
            raise ValueError(f"Chunks artifact must contain an object: {chunks_path.name}")
        chunks = raw_artifact.get("chunks")
        if not isinstance(chunks, list):
            raise ValueError(f"Chunks artifact is missing a chunks list: {chunks_path.name}")
        if not all(isinstance(chunk, dict) for chunk in chunks):
            raise ValueError(f"Chunks artifact contains an invalid chunk: {chunks_path.name}")
        return raw_artifact, chunks

    def _delete_document_points(
        self, *, collection_name: str, source: str, scope: str
    ) -> None:
        """Remove existing points for exactly one source and scope before replacement."""
        point_filter = Filter(
            must=[
                FieldCondition(key="source", match=MatchValue(value=source)),
                FieldCondition(key="scope", match=MatchValue(value=scope)),
            ]
        )
        self.client.delete(
            collection_name=collection_name,
            points_selector=FilterSelector(filter=point_filter),
        )

    def index_chunks_path(
        self,
        chunks_path: str | Path,
        *,
        scope: str,
        collection_name: str,
    ) -> int:
        """Replace and index one persisted Stage 4 artifact in its explicit scope.

        The point ID is deterministic over collection, scope, source, and original
        chunk index. Repeating this call therefore cannot create duplicate vectors.
        """
        if not scope.strip():
            raise ValueError("scope is required for vector indexing")
        if not collection_name.strip():
            raise ValueError("collection_name is required for vector indexing")

        artifact_path = Path(chunks_path)
        artifact, chunks = self._load_chunks(artifact_path)
        source = self._source_from_artifact(artifact, artifact_path)

        indexable_chunks: list[tuple[int, Dict[str, Any]]] = []
        filter_boilerplate = bool(
            self.config.get("chunking", {}).get("filter_boilerplate", True)
        )
        for chunk_index, chunk in enumerate(chunks):
            content = chunk.get("content")
            if not isinstance(content, str) or not content.strip():
                raise ValueError(
                    f"Chunk {chunk_index} has no indexable content: {artifact_path.name}"
                )
            if filter_boilerplate and chunk.get("is_boilerplate", False):
                continue
            indexable_chunks.append((chunk_index, chunk))

        if not indexable_chunks:
            self._ensure_collection(collection_name)
            self._delete_document_points(
                collection_name=collection_name, source=source, scope=scope
            )
            log.info(
                "No indexable chunks source=%s scope=%s collection=%s",
                source,
                scope,
                collection_name,
            )
            return 0

        contents = [chunk["content"] for _, chunk in indexable_chunks]
        embeddings: Any = self.embedding_model.encode(
            contents,
            normalize_embeddings=self._normalize_embeddings,
        )
        if hasattr(embeddings, "tolist"):
            embeddings = embeddings.tolist()
        if not isinstance(embeddings, list) or len(embeddings) != len(indexable_chunks):
            raise ValueError(
                f"Embedding model returned an unexpected result for {artifact_path.name}"
            )

        points: list[PointStruct] = []
        for (chunk_index, chunk), embedding in zip(indexable_chunks, embeddings):
            point_id = uuid.uuid5(
                _POINT_ID_NAMESPACE,
                f"{collection_name}:{scope}:{source}:{chunk_index}",
            )
            points.append(
                PointStruct(
                    id=str(point_id),
                    vector=embedding,
                    payload={
                        "source": source,
                        "scope": scope,
                        "content": chunk["content"],
                        "context": chunk.get("context", ""),
                        "level": chunk.get("level", 0),
                        "chunk_index": chunk_index,
                        "page_number": chunk.get("page_number", 1),
                    },
                )
            )

        self._ensure_collection(collection_name)
        self._delete_document_points(
            collection_name=collection_name, source=source, scope=scope
        )
        for batch in _batched(points, self._batch_size):
            self.client.upsert(collection_name=collection_name, points=batch)

        log.info(
            "Indexed chunks=%s source=%s scope=%s collection=%s",
            len(points),
            source,
            scope,
            collection_name,
        )
        return len(points)

    def process_file(
        self, file_path: str | Path, *, scope: str, collection_name: str
    ) -> int:
        """Compatibility alias for indexing a single persisted chunks artifact."""
        return self.index_chunks_path(
            file_path, scope=scope, collection_name=collection_name
        )

    def run(
        self, input_dir_path: str | Path, *, scope: str, collection_name: str
    ) -> int:
        """Index only Stage 4 artifacts in a directory under an explicit scope."""
        artifact_dir = Path(input_dir_path)
        if not artifact_dir.exists():
            raise FileNotFoundError(f"Chunks directory not found: {artifact_dir}")

        artifact_paths = sorted(artifact_dir.rglob("*_chunks.json"))
        indexed_count = 0
        for chunks_path in artifact_paths:
            indexed_count += self.index_chunks_path(
                chunks_path, scope=scope, collection_name=collection_name
            )
        log.info(
            "Indexed chunks=%s artifacts=%s scope=%s collection=%s",
            indexed_count,
            len(artifact_paths),
            scope,
            collection_name,
        )
        return indexed_count


def _batched(points: list[PointStruct], size: int) -> Iterable[list[PointStruct]]:
    """Yield non-empty bounded point batches."""
    if size < 1:
        raise ValueError("vectorization.batch_size must be at least 1")
    for start in range(0, len(points), size):
        yield points[start : start + size]


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Index persisted Stage 4 chunks artifacts using Qdrant"
    )
    parser.add_argument("-c", "--config", help="Path to config YAML file")
    parser.add_argument(
        "-i", "--input-dir", required=True, help="Directory containing *_chunks.json files"
    )
    parser.add_argument("--scope", required=True, help="Explicit document scope")
    parser.add_argument(
        "--collection", required=True, help="Explicit target Qdrant collection"
    )
    args = parser.parse_args()

    config = ConfigLoader.load(args.config) if args.config else ConfigLoader.load()
    vectorizer = MedicalVectorizer(config=config)
    indexed = vectorizer.run(
        args.input_dir, scope=args.scope, collection_name=args.collection
    )
    log.info("Vectorization complete indexed_chunks=%s", indexed)
