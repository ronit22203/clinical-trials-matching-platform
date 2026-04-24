"""
retrieval_evaluator.py — Recall@K, Precision@K, NDCG@K, MRR, HitRate with bootstrap CIs.

Uses Qdrant directly (bypasses the agent layer) for deterministic, reproducible queries.

Usage:
    python evaluators/retrieval_evaluator.py \\
        --golden golden/queries.json \\
        --output results/<RUN_DIR>/retrieval.json \\
        [--qdrant-url http://localhost:6333] \\
        [--collection medical_papers] \\
        [--embedding-model BAAI/bge-small-en-v1.5] \\
        [--top-k 10] \\
        [--bootstrap-resamples 1000]
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BENCHMARKING_DIR = Path(__file__).resolve().parents[1]
_RUN_ID_ENV = "BENCH_RUN_ID"


# ---------------------------------------------------------------------------
# Metric helpers
# ---------------------------------------------------------------------------

def _relevance_grade(chunk_index: int, relevance_grades: dict[str, int]) -> int:
    key = f"chunk_{chunk_index:02d}"
    return relevance_grades.get(key, 0)


def _recall_at_k(ranked_grades: list[int], k: int, total_relevant: int) -> float:
    if total_relevant == 0:
        return 0.0
    hits = sum(1 for g in ranked_grades[:k] if g > 0)
    return hits / total_relevant


def _precision_at_k(ranked_grades: list[int], k: int) -> float:
    if k == 0:
        return 0.0
    relevant = sum(1 for g in ranked_grades[:k] if g > 0)
    return relevant / k


def _ndcg_at_k(ranked_grades: list[int], k: int) -> float:
    """Normalized Discounted Cumulative Gain using 2-level relevance (0,1,2)."""
    def dcg(grades: list[int], n: int) -> float:
        return sum(
            (2 ** g - 1) / math.log2(i + 2)
            for i, g in enumerate(grades[:n])
        )

    actual_dcg = dcg(ranked_grades, k)
    ideal_grades = sorted(ranked_grades, reverse=True)
    ideal_dcg = dcg(ideal_grades, k)
    return actual_dcg / ideal_dcg if ideal_dcg > 0 else 0.0


def _reciprocal_rank(ranked_grades: list[int]) -> float:
    for i, g in enumerate(ranked_grades):
        if g > 0:
            return 1.0 / (i + 1)
    return 0.0


def _hit_at_k(ranked_grades: list[int], k: int) -> float:
    return 1.0 if any(g > 0 for g in ranked_grades[:k]) else 0.0


# ---------------------------------------------------------------------------
# Bootstrap CI
# ---------------------------------------------------------------------------

def _bootstrap_ci(
    values: list[float],
    n_resamples: int = 1000,
    confidence: float = 0.95,
    rng: np.random.Generator | None = None,
) -> dict[str, float]:
    """Bootstrap percentile CI for the mean of *values*."""
    if rng is None:
        rng = np.random.default_rng(seed=42)
    arr = np.array(values)
    means = np.array([rng.choice(arr, size=len(arr), replace=True).mean() for _ in range(n_resamples)])
    alpha = (1 - confidence) / 2
    lower, upper = float(np.quantile(means, alpha)), float(np.quantile(means, 1 - alpha))
    return {"lower": lower, "upper": upper, "confidence": confidence}


# ---------------------------------------------------------------------------
# Qdrant querier
# ---------------------------------------------------------------------------

def _load_env() -> dict[str, str]:
    env_file = _REPO_ROOT / ".env.local"
    env: dict[str, str] = {}
    if not env_file.exists():
        return env
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _resolve_env_str(val: str, env: dict[str, str]) -> str:
    return re.sub(r"\$\{([^}]+)\}", lambda m: env.get(m.group(1), ""), val)


class RetrievalEvaluator:
    def __init__(
        self,
        qdrant_url: str,
        collection: str,
        embedding_model: str,
        top_k: int = 10,
        bootstrap_resamples: int = 1000,
    ) -> None:
        self.qdrant_url = qdrant_url
        self.collection = collection
        self.embedding_model_name = embedding_model
        self.top_k = top_k
        self.bootstrap_resamples = bootstrap_resamples
        self._qdrant = None
        self._model = None

    def _get_qdrant(self):
        if self._qdrant is None:
            from qdrant_client import QdrantClient
            self._qdrant = QdrantClient(self.qdrant_url)
        return self._qdrant

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            cache_dir = str(_REPO_ROOT / "data" / "models")
            self._model = SentenceTransformer(
                self.embedding_model_name,
                cache_folder=cache_dir,
            )
        return self._model

    def _query(self, text: str) -> list[dict[str, Any]]:
        vec = self._get_model().encode(text).tolist()
        hits = self._get_qdrant().query_points(
            collection_name=self.collection,
            query=vec,
            limit=self.top_k,
        ).points
        return [
            {
                "rank": i + 1,
                "chunk_index": h.payload.get("chunk_index", -1),
                "score": round(h.score, 6),
                "source": h.payload.get("source", ""),
                "page_number": h.payload.get("page_number"),
                "content_preview": h.payload.get("content", "")[:80],
            }
            for i, h in enumerate(hits)
        ]

    def evaluate_query(self, query: dict[str, Any]) -> dict[str, Any]:
        qid = query["id"]
        qtext = query["text"]
        relevance_grades: dict[str, int] = query.get("relevance_grades", {})
        total_relevant = sum(1 for g in relevance_grades.values() if g > 0)

        log.info("  [%s] %s", qid, qtext[:70])
        retrieved = self._query(qtext)

        ranked_grades = [
            _relevance_grade(r["chunk_index"], relevance_grades)
            for r in retrieved
        ]

        # Annotate retrieved with relevance grade
        for r, g in zip(retrieved, ranked_grades):
            r["relevance_grade"] = g

        r1 = _recall_at_k(ranked_grades, 1, total_relevant)
        r3 = _recall_at_k(ranked_grades, 3, total_relevant)
        r5 = _recall_at_k(ranked_grades, 5, total_relevant)
        r10 = _recall_at_k(ranked_grades, 10, total_relevant)
        p5 = _precision_at_k(ranked_grades, 5)
        ndcg5 = _ndcg_at_k(ranked_grades, 5)
        rr = _reciprocal_rank(ranked_grades)
        hit5 = _hit_at_k(ranked_grades, 5)

        return {
            "query_id": qid,
            "category": query.get("category", "unknown"),
            "text": qtext,
            "total_relevant_in_golden": total_relevant,
            "retrieved_chunks": retrieved,
            "recall_at_1": r1,
            "recall_at_3": r3,
            "recall_at_5": r5,
            "recall_at_10": r10,
            "precision_at_5": p5,
            "ndcg_at_5": ndcg5,
            "rr": rr,
            "hit_at_5": hit5,
        }

    def run(self, golden_path: Path, output_path: Path, run_id: str) -> dict[str, Any]:
        with open(golden_path) as f:
            golden = json.load(f)

        queries = golden["queries"]
        log.info("Evaluating %d queries against collection '%s'", len(queries), self.collection)

        per_query: list[dict[str, Any]] = []
        t0 = time.perf_counter()
        for q in queries:
            per_query.append(self.evaluate_query(q))
        elapsed = time.perf_counter() - t0

        rng = np.random.default_rng(seed=42)

        def _agg(metric: str) -> dict[str, Any]:
            vals = [r[metric] for r in per_query]
            mean_val = float(np.mean(vals))
            ci = _bootstrap_ci(vals, self.bootstrap_resamples, rng=rng)
            return {"value": mean_val, "ci": ci}

        aggregate = {
            "recall_at_1": _agg("recall_at_1"),
            "recall_at_3": _agg("recall_at_3"),
            "recall_at_5": _agg("recall_at_5"),
            "recall_at_10": _agg("recall_at_10"),
            "precision_at_5": _agg("precision_at_5"),
            "ndcg_at_5": _agg("ndcg_at_5"),
            "mrr": _agg("rr"),
            "hit_rate_at_5": _agg("hit_at_5"),
        }

        result: dict[str, Any] = {
            "run_id": run_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": round(elapsed, 2),
            "config": {
                "collection": self.collection,
                "embedding_model": self.embedding_model_name,
                "top_k": self.top_k,
                "bootstrap_resamples": self.bootstrap_resamples,
            },
            "aggregate": aggregate,
            "per_query": per_query,
        }

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(result, f, indent=2)

        log.info("Retrieval results written → %s", output_path)
        _print_summary(aggregate)
        return result


def _print_summary(agg: dict[str, Any]) -> None:
    print("\n── Retrieval Summary ────────────────────────────────")
    rows = [
        ("Recall@1",    agg["recall_at_1"]),
        ("Recall@3",    agg["recall_at_3"]),
        ("Recall@5",    agg["recall_at_5"]),
        ("Recall@10",   agg["recall_at_10"]),
        ("Precision@5", agg["precision_at_5"]),
        ("NDCG@5",      agg["ndcg_at_5"]),
        ("MRR",         agg["mrr"]),
        ("HitRate@5",   agg["hit_rate_at_5"]),
    ]
    print(f"  {'Metric':<14} {'Value':>7}   {'95% CI'}")
    print(f"  {'-'*14} {'-'*7}   {'-'*20}")
    for name, m in rows:
        v = m["value"]
        lo = m["ci"]["lower"]
        hi = m["ci"]["upper"]
        print(f"  {name:<14} {v:>6.1%}   [{lo:.1%}–{hi:.1%}]")
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Retrieval evaluator with bootstrap CIs")
    p.add_argument("--golden", required=True, help="Path to golden/queries.json")
    p.add_argument("--output", required=True, help="Path to write retrieval.json")
    p.add_argument("--run-id", default=os.environ.get(_RUN_ID_ENV, f"bench_{int(time.time())}"))
    p.add_argument("--qdrant-url", default=None)
    p.add_argument("--collection", default=None)
    p.add_argument("--embedding-model", default=None)
    p.add_argument("--top-k", type=int, default=10)
    p.add_argument("--bootstrap-resamples", type=int, default=1000)
    return p


def main() -> None:
    import yaml

    args = _build_parser().parse_args()

    env = _load_env()
    cfg_path = _REPO_ROOT / "config" / "app.yaml"
    with open(cfg_path) as f:
        app_cfg: dict[str, Any] = yaml.safe_load(f) or {}

    def _resolve(val: str) -> str:
        return _resolve_env_str(val, env)

    services = app_cfg.get("services", {})
    default_url = _resolve(services.get("qdrant", {}).get("url", "http://localhost:6333"))
    default_coll = services.get("qdrant", {}).get("collection", "medical_papers")

    ar_tools = app_cfg.get("agentic_reasoning", {}).get("tools", {})
    gr_cfg = ar_tools.get("graphrag", {}).get("config", {})
    default_model = gr_cfg.get("embedding_model", "BAAI/bge-small-en-v1.5")

    evaluator = RetrievalEvaluator(
        qdrant_url=args.qdrant_url or default_url,
        collection=args.collection or default_coll,
        embedding_model=args.embedding_model or default_model,
        top_k=args.top_k,
        bootstrap_resamples=args.bootstrap_resamples,
    )
    evaluator.run(
        golden_path=Path(args.golden),
        output_path=Path(args.output),
        run_id=args.run_id,
    )


if __name__ == "__main__":
    main()
