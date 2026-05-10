"""
GraphRAG tool: hybrid retrieval combining Qdrant vector search with Neo4j graph context.

Heavy dependencies (qdrant_client, neo4j, sentence_transformers) are imported lazily
so the tool registry can load this module without requiring all deps to be installed.
"""
import logging
import re
from typing import Any, Dict, List

from .base import BaseTool

logger = logging.getLogger(__name__)

# Common words that add noise to entity/keyword matching
_STOP_WORDS = {
    "what", "are", "the", "is", "a", "an", "of", "for", "in", "on", "at",
    "to", "and", "or", "with", "by", "from", "tell", "me", "about", "list",
    "show", "find", "give", "search", "get", "how", "does", "do", "can",
    "will", "has", "have", "been", "be", "was", "were", "any", "all", "some",
}


def _extract_keywords(query: str, max_keywords: int = 5) -> List[str]:
    """Extract meaningful keywords from a natural-language query."""
    words = re.findall(r"\b[a-zA-Z][a-zA-Z0-9\-]+\b", query)
    return [w for w in words if w.lower() not in _STOP_WORDS and len(w) > 2][:max_keywords]


class GraphRAGTool(BaseTool):
    """
    Hybrid retrieval: Qdrant semantic search + Neo4j knowledge-graph enrichment.

    Vector search casts a wide net over document chunks; the graph layer
    adds structured entity relationships keyed on keywords from the query.
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        # Lazy-init — clients are created on first use
        self._qdrant = None
        self._embedder = None
        self._driver = None
        self._reranker = None

    @property
    def description(self) -> str:
        return (
            "Search medical literature and clinical documents using hybrid "
            "vector + knowledge graph retrieval. Input should be a natural "
            "language query about a clinical topic, drug, condition, or study."
        )

    # ------------------------------------------------------------------
    # Lazy client accessors
    # ------------------------------------------------------------------

    def _qdrant_client(self):
        if self._qdrant is None:
            from qdrant_client import QdrantClient
            self._qdrant = QdrantClient(self.config["qdrant_url"])
        return self._qdrant

    def _embedder_model(self):
        if self._embedder is None:
            from sentence_transformers import SentenceTransformer
            cache_dir = self.config.get("model_cache_dir", "data/models")
            self._embedder = SentenceTransformer(
                self.config["embedding_model"],
                cache_folder=cache_dir,
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
        """Lazy-load CrossEncoder reranker. Returns None when reranker_model is not configured."""
        model_name = self.config.get("reranker_model")
        if not model_name:
            return None
        if self._reranker is None:
            from sentence_transformers import CrossEncoder
            cache_dir = self.config.get("model_cache_dir", "data/models")
            logger.info("Loading reranker: %s", model_name)
            self._reranker = CrossEncoder(model_name, cache_folder=cache_dir)
        return self._reranker

    # ------------------------------------------------------------------
    # Retrieval helpers
    # ------------------------------------------------------------------

    def _vector_search(self, query: str, fetch_limit: int) -> List[Dict]:
        query_vector = self._embedder_model().encode(query).tolist()
        hits = self._qdrant_client().query_points(
            collection_name=self.config["collection"],
            query=query_vector,
            limit=fetch_limit,
        ).points
        return [
            {
                "score": round(hit.score, 4),
                "content": hit.payload.get("content", ""),
                "source": hit.payload.get("source", ""),
                "chunk_id": hit.payload.get("chunk_id"),
                "chunk_index": hit.payload.get("chunk_index"),
                "context": hit.payload.get("context"),
            }
            for hit in hits
        ]

    def _graph_context(self, keywords: List[str], limit: int) -> List[str]:
        """Return entity–relation–entity triples whose head or tail matches any keyword."""
        if not keywords:
            return []
        cypher = """
            MATCH (h)-[r]->(t)
            WHERE any(kw IN $keywords
                      WHERE toLower(h.name) CONTAINS toLower(kw)
                         OR toLower(t.name) CONTAINS toLower(kw))
            RETURN h.name AS head, type(r) AS relation, t.name AS tail
            LIMIT $limit
        """
        try:
            with self._neo4j_driver().session() as session:
                records = list(session.run(cypher, keywords=keywords, limit=limit))
            return [f"{r['head']} --[{r['relation']}]--> {r['tail']}" for r in records]
        except Exception as exc:
            logger.warning("Neo4j query failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # BaseTool interface
    # ------------------------------------------------------------------

    def execute(self, input: Any) -> Any:
        query = input if isinstance(input, str) else input.get("query", "")
        if not query.strip():
            return "Error: No query provided."

        limit: int = self.config.get("limit", 3)
        neo4j_limit: int = self.config.get("neo4j_limit", 10)
        reranker = self._reranker_model()

        # Over-fetch when reranking so the reranker has candidates to choose from.
        if reranker is not None:
            cfg_retrieval_k = self.config.get("retrieval_k")
            fetch_limit: int = cfg_retrieval_k if cfg_retrieval_k else limit * 2
        else:
            fetch_limit = limit

        keywords = _extract_keywords(query)

        try:
            candidates = self._vector_search(query, fetch_limit)
        except Exception as exc:
            logger.error("Vector search failed: %s", exc)
            return f"Error: Vector search failed — {exc}"

        if reranker is not None and candidates:
            pairs = [(query, c["content"]) for c in candidates]
            scores: List[float] = reranker.predict(pairs).tolist()
            for c, s in zip(candidates, scores):
                c["reranker_score"] = round(s, 6)
            candidates.sort(key=lambda c: c["reranker_score"], reverse=True)
            logger.info(
                "Reranker (%s) scored %d candidates → returning top %d",
                self.config["reranker_model"], len(candidates), limit,
            )

        vector_results = candidates[:limit]

        graph_facts = self._graph_context(keywords, neo4j_limit)

        return {
            "found": bool(vector_results or graph_facts),
            "source": "graphrag",
            "query": query,
            "keywords": keywords,
            "vector_results": vector_results,
            "graph_facts": graph_facts,
        }

