"""
GraphRAG tool: hybrid retrieval combining Qdrant vector search with Neo4j graph context.

Heavy dependencies (qdrant_client, neo4j, sentence_transformers) are imported lazily
so the tool registry can load this module without requiring all deps to be installed.
"""
from __future__ import annotations

import logging
from pathlib import Path
import re
from typing import Any

from .base import BaseTool

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_STOP_WORDS = {
    "what", "are", "the", "is", "a", "an", "of", "for", "in", "on", "at",
    "to", "and", "or", "with", "by", "from", "tell", "me", "about", "list",
    "show", "find", "give", "search", "get", "how", "does", "do", "can",
    "will", "has", "have", "been", "be", "was", "were", "any", "all", "some",
}
_DOCUMENT_REFERENCE_RE = re.compile(r"\[([^\[\]\r\n]{1,255})\]")
_DOCUMENT_REFERENCE_WORDS = {
    "document",
    "file",
    "image",
    "prescription",
    "record",
    "scan",
    "scanned",
}
_SOURCE_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}
_MAX_RESULT_LIMIT = 50


class GraphRAGUnavailableError(RuntimeError):
    """Raised when a configured retrieval dependency cannot serve a request."""


def _extract_keywords(query: str, max_keywords: int = 5) -> list[str]:
    """Extract meaningful keywords from a natural-language query."""
    words = re.findall(r"\b[a-zA-Z][a-zA-Z0-9\-]+\b", query)
    return [w for w in words if w.lower() not in _STOP_WORDS and len(w) > 2][:max_keywords]


def _looks_like_document_reference(value: str) -> bool:
    words = {word.lower() for word in re.findall(r"[a-zA-Z]+", value)}
    return (
        "_" in value
        or Path(value).suffix.lower() in _SOURCE_SUFFIXES
        or bool(words & _DOCUMENT_REFERENCE_WORDS)
    )


def _source_identity(value: str) -> str:
    name = Path(value.strip()).name
    stem = Path(name).stem if Path(name).suffix.lower() in _SOURCE_SUFFIXES else name
    return re.sub(r"[\s_-]+", " ", stem).strip().casefold()


def _extract_source_reference(
    query: str,
    active_source: str | None,
) -> tuple[str, tuple[int, int]] | None:
    """Return the first filename-like bracket reference and its query span."""
    active_identity = _source_identity(active_source) if active_source else None
    for match in _DOCUMENT_REFERENCE_RE.finditer(query):
        value = match.group(1).strip()
        if not value:
            continue
        if _looks_like_document_reference(value) or (
            active_identity is not None and _source_identity(value) == active_identity
        ):
            return value, match.span()
    return None


def _empty_outcome(code: str, message: str, action: str) -> dict[str, str]:
    return {"code": code, "message": message, "action": action}


class GraphRAGTool(BaseTool):
    """Hybrid retrieval over one explicitly selected clinical data target."""

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self._qdrant = None
        self._embedder = None
        self._driver = None
        self._reranker = None

    @property
    def description(self) -> str:
        return (
            "Search medical literature or one active clinical document using "
            "vector retrieval plus source-scoped knowledge graph enrichment."
        )

    def _qdrant_client(self):
        if self._qdrant is None:
            from qdrant_client import QdrantClient

            self._qdrant = QdrantClient(self.config["qdrant_url"])
        return self._qdrant

    def _model_cache_dir(self) -> str:
        configured = Path(self.config.get("model_cache_dir", "data/models")).expanduser()
        cache_dir = configured if configured.is_absolute() else _REPO_ROOT / configured
        cache_dir.mkdir(parents=True, exist_ok=True)
        return str(cache_dir)

    def _embedder_model(self):
        if self._embedder is None:
            from sentence_transformers import SentenceTransformer

            self._embedder = SentenceTransformer(
                self.config["embedding_model"],
                cache_folder=self._model_cache_dir(),
            )
        return self._embedder

    def _neo4j_driver(self):
        if self._driver is None:
            from neo4j import GraphDatabase

            self._driver = GraphDatabase.driver(
                self.config["neo4j_uri"],
                auth=(self.config["neo4j_username"], self.config["neo4j_password"]),
            )
        return self._driver

    def _reranker_model(self):
        model_name = self.config.get("reranker_model")
        if not model_name:
            return None
        if self._reranker is None:
            from sentence_transformers import CrossEncoder

            logger.info("Loading reranker: %s", model_name)
            self._reranker = CrossEncoder(
                model_name,
                cache_folder=self._model_cache_dir(),
            )
        return self._reranker

    def warmup(self) -> None:
        """Load retrieval models before the first user query."""
        logger.info("Pre-warming GraphRAG embedding model")
        self._embedder_model()
        if self.config.get("reranker_model"):
            logger.info("Pre-warming GraphRAG reranker")
            self._reranker_model()
        logger.info("GraphRAG retrieval models ready")

    def _target_config(self, target_name: str) -> dict[str, str]:
        configured = self.config.get("retrieval_targets")
        if configured:
            for target in configured:
                if isinstance(target, dict) and target.get("name") == target_name:
                    collection = target.get("collection")
                    scope = target.get("scope")
                    if isinstance(collection, str) and isinstance(scope, str):
                        return {
                            "name": target_name,
                            "collection": collection,
                            "scope": scope,
                        }
            raise ValueError(f"Unknown retrieval target: {target_name}")

        legacy_scope = self.config.get("scope", "literature")
        if target_name != legacy_scope:
            raise ValueError(f"Unknown retrieval target: {target_name}")
        return {
            "name": legacy_scope,
            "collection": self.config["collection"],
            "scope": legacy_scope,
        }

    def _vector_search(
        self,
        query: str,
        fetch_limit: int,
        target: dict[str, str],
        source: str | None,
    ) -> list[dict]:
        from qdrant_client.http.models import FieldCondition, Filter, MatchValue

        from ..monitoring.metrics import (
            observe_embed_query,
            observe_qdrant_query,
            timed_seconds,
        )

        embed_started = timed_seconds()
        encoded_query = self._embedder_model().encode(query)
        observe_embed_query(timed_seconds() - embed_started)
        query_vector = (
            encoded_query.tolist()
            if hasattr(encoded_query, "tolist")
            else list(encoded_query)
        )
        client = self._qdrant_client()
        collection = target["collection"]
        if not client.collection_exists(collection):
            raise GraphRAGUnavailableError(
                f"Configured Qdrant collection is unavailable: {collection}"
            )

        conditions = [
            FieldCondition(
                key="scope",
                match=MatchValue(value=target["scope"]),
            )
        ]
        if source:
            conditions.append(
                FieldCondition(
                    key="source",
                    match=MatchValue(value=source),
                )
            )

        query_started = timed_seconds()
        hits = client.query_points(
            collection_name=collection,
            query=query_vector,
            limit=fetch_limit,
            query_filter=Filter(must=conditions),
        ).points
        observe_qdrant_query(
            collection=collection,
            duration_seconds=timed_seconds() - query_started,
        )
        results: list[dict] = []
        for hit in hits:
            payload = hit.payload or {}
            results.append(
                {
                    "score": round(hit.score, 4),
                    "content": payload.get("content", ""),
                    "source": payload.get("source", ""),
                    "chunk_id": payload.get("chunk_id"),
                    "chunk_index": payload.get("chunk_index"),
                    "context": payload.get("context"),
                    "page_number": payload.get("page_number"),
                    "char_start": payload.get("char_start"),
                    "char_end": payload.get("char_end"),
                    "scope": payload.get("scope", target["scope"]),
                    "collection": collection,
                }
            )
        return results

    def _graph_context(
        self,
        keywords: list[str],
        limit: int,
        target: dict[str, str],
        graph_source: str | None,
    ) -> list[str]:
        """Return source-scoped entity relationships matching the query keywords."""
        if not keywords:
            return []
        from neo4j.exceptions import Neo4jError

        cypher = """
            MATCH (h)-[r]->(t)
            WHERE r.scope = $scope
              AND ($source IS NULL OR r.source = $source)
              AND any(kw IN $keywords
                      WHERE toLower(h.name) CONTAINS toLower(kw)
                         OR toLower(t.name) CONTAINS toLower(kw))
            RETURN h.name AS head, type(r) AS relation, t.name AS tail
            LIMIT $limit
        """
        from ..monitoring.metrics import observe_neo4j_query, timed_seconds

        neo4j_started = timed_seconds()
        try:
            with self._neo4j_driver().session() as session:
                records = list(
                    session.run(
                        cypher,
                        keywords=keywords,
                        limit=limit,
                        scope=target["scope"],
                        source=graph_source,
                    )
                )
        except (Neo4jError, ConnectionError, OSError, TimeoutError) as exc:
            observe_neo4j_query(timed_seconds() - neo4j_started)
            logger.warning(
                "Neo4j enrichment unavailable: target=%s error=%s",
                target["name"],
                type(exc).__name__,
            )
            return []
        observe_neo4j_query(timed_seconds() - neo4j_started)
        return [f"{record['head']} --[{record['relation']}]--> {record['tail']}" for record in records]

    def _parse_request(
        self,
        input: Any,
    ) -> tuple[str, str, str | None, str | None, int] | str:
        if isinstance(input, str):
            query = input
            target_name = self.config.get("scope", "literature")
            source = None
            source_slug = None
            limit = self.config.get("limit", 3)
        elif isinstance(input, dict):
            query = input.get("query", "")
            target_name = input.get("target", self.config.get("scope", "literature"))
            source = input.get("source")
            source_slug = input.get("source_slug")
            limit = input.get("limit", self.config.get("limit", 3))
        else:
            return "Error: Retrieval input must be a query string or mapping."

        if not isinstance(query, str) or not query.strip():
            return "Error: No query provided."
        if not isinstance(target_name, str) or not target_name.strip():
            return "Error: target must be a non-empty string."
        if source is not None and (not isinstance(source, str) or not source.strip()):
            return "Error: source must be a non-empty filename."
        if source_slug is not None and (
            not isinstance(source_slug, str) or not source_slug.strip()
        ):
            return "Error: source_slug must be a non-empty string."
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= _MAX_RESULT_LIMIT:
            return f"Error: limit must be an integer between 1 and {_MAX_RESULT_LIMIT}."
        return query.strip(), target_name.strip(), source, source_slug, limit

    def execute(self, input: Any) -> Any:
        parsed = self._parse_request(input)
        if isinstance(parsed, str):
            return parsed
        query, target_name, source, source_slug, limit = parsed

        try:
            target = self._target_config(target_name)
        except ValueError as exc:
            return f"Error: {exc}"

        if target_name == "patient_context" and source is None:
            return "Error: patient_context retrieval requires an exact source filename."
        if target_name != "patient_context" and (source is not None or source_slug is not None):
            return "Error: source context is only valid for patient_context retrieval."

        source_reference = _extract_source_reference(query, source)
        semantic_query = query
        if source_reference is not None:
            referenced_source, span = source_reference
            if source is not None and _source_identity(referenced_source) != _source_identity(source):
                return {
                    "found": False,
                    "source": "graphrag",
                    "query": query,
                    "keywords": [],
                    "vector_results": [],
                    "graph_facts": [],
                    "graph_anchor": None,
                    "retrieval_context": {
                        **target,
                        "source": source,
                        "source_slug": source_slug,
                    },
                    "empty": _empty_outcome(
                        "source_mismatch",
                        (
                            f"The query references '{referenced_source}', but the active "
                            f"document is '{source}'."
                        ),
                        "Update the query or upload the referenced document.",
                    ),
                }
            semantic_query = f"{query[:span[0]]} {query[span[1]:]}".strip() or query

        neo4j_limit = int(self.config.get("neo4j_limit", 10))
        reranker = self._reranker_model()
        if reranker is not None:
            retrieval_k = int(self.config.get("retrieval_k") or 0)
            fetch_limit = max(retrieval_k, limit * 2)
        else:
            fetch_limit = limit

        keywords = _extract_keywords(semantic_query)
        try:
            candidates = self._vector_search(
                semantic_query,
                fetch_limit,
                target,
                source,
            )
        except GraphRAGUnavailableError:
            raise
        except (ConnectionError, OSError, RuntimeError, TimeoutError, ValueError) as exc:
            raise GraphRAGUnavailableError(
                f"Vector retrieval failed: {type(exc).__name__}: {exc}"
            ) from exc

        raw_candidate_count = len(candidates)
        min_relevance_score = float(self.config.get("min_relevance_score", 0.35))
        candidates = [
            candidate
            for candidate in candidates
            if candidate["score"] >= min_relevance_score
        ]

        if reranker is not None and candidates:
            from ..monitoring.metrics import observe_rerank, timed_seconds

            pairs = [(semantic_query, candidate["content"]) for candidate in candidates]
            rerank_started = timed_seconds()
            predicted_scores = reranker.predict(pairs)
            observe_rerank(timed_seconds() - rerank_started)
            scores = (
                predicted_scores.tolist()
                if hasattr(predicted_scores, "tolist")
                else list(predicted_scores)
            )
            for candidate, score in zip(candidates, scores):
                candidate["reranker_score"] = round(float(score), 6)
            candidates.sort(
                key=lambda candidate: candidate["reranker_score"],
                reverse=True,
            )

        vector_results = candidates[:limit]
        resolved_slug = source_slug or (Path(source).stem if source else None)
        graph_source = f"{resolved_slug}_chunks" if resolved_slug else None
        graph_facts = self._graph_context(
            keywords,
            neo4j_limit,
            target,
            graph_source,
        )
        graph_anchor = None
        if graph_facts:
            match = re.match(r"^(.+?)\s+--\[", graph_facts[0].strip())
            if match:
                graph_anchor = match.group(1).strip()

        empty = None
        if not vector_results and not graph_facts:
            if target_name == "patient_context" and raw_candidate_count == 0:
                empty = _empty_outcome(
                    "source_not_indexed",
                    "The active document is not available in the patient search index.",
                    "Process the document again, then retry the query.",
                )
            else:
                location = "the active document" if source else "the literature index"
                empty = _empty_outcome(
                    "no_relevant_evidence",
                    f"No relevant evidence was found in {location}.",
                    "Use more specific clinical terms or verify that the source contains the requested information.",
                )

        logger.info(
            "GraphRAG retrieval complete: target=%s raw_candidates=%d vector_results=%d graph_facts=%d",
            target_name,
            raw_candidate_count,
            len(vector_results),
            len(graph_facts),
        )
        return {
            "found": bool(vector_results or graph_facts),
            "source": "graphrag",
            "query": query,
            "keywords": keywords,
            "vector_results": vector_results,
            "graph_facts": graph_facts,
            "graph_anchor": graph_anchor,
            "retrieval_context": {
                **target,
                "source": source,
                "source_slug": source_slug,
            },
            "empty": empty,
        }
