"""
reasoning_evaluator.py — End-to-end agent quality benchmark.

Runs every golden query through the two-phase Agent pipeline:
  Phase 1: GraphRAG retrieval (mandatory, timed separately)
  Phase 2: Grounded LLM synthesis

Captures per-query: found flag, latency (end-to-end + phase-1 only),
vector hits, graph facts count, synthesis length.

Aggregate: found_rate, latency percentiles, mean evidence density.

This evaluator is distinct from retrieval_evaluator.py (which queries Qdrant
directly). Here we go through the full Agent path to measure real pipeline
behaviour, including any synthesis failures.

Usage:
    python evaluators/reasoning_evaluator.py \\
        --queries golden/queries.json \\
        --output results/<RUN_DIR>/reasoning.json \\
        [--config ../../config/app.yaml]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
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

_BENCHMARKING_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = _BENCHMARKING_DIR.parent
_REASONING_DIR = _REPO_ROOT / "agentic-reasoning"
_RUN_ID_ENV = "BENCH_RUN_ID"


def _add_reasoning_to_path() -> None:
    """Make agentic-reasoning importable without requiring it on PYTHONPATH."""
    reasoning_path = str(_REASONING_DIR)
    if reasoning_path not in sys.path:
        sys.path.insert(0, reasoning_path)


def _percentiles(data: list[float]) -> dict[str, float]:
    if not data:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "min": 0.0, "max": 0.0, "mean": 0.0, "std": 0.0}
    arr = np.array(data)
    return {
        "p50": float(np.percentile(arr, 50)),
        "p95": float(np.percentile(arr, 95)),
        "p99": float(np.percentile(arr, 99)),
        "min": float(arr.min()),
        "max": float(arr.max()),
        "mean": float(arr.mean()),
        "std": float(arr.std()),
    }


def _run_query(agent, query_text: str) -> dict[str, Any]:
    """Run one query through the agent. Returns per-query result dict."""
    t0 = time.perf_counter()
    try:
        result = agent.run(query_text)
        latency_ms = (time.perf_counter() - t0) * 1000

        evidence = result.evidence if isinstance(result.evidence, dict) else {}
        vector_hits = len(evidence.get("vector_results", []))
        graph_facts = len(evidence.get("graph_facts", []))

        return {
            "found": result.found,
            "latency_ms": round(latency_ms, 1),
            "vector_hits": vector_hits,
            "graph_facts": graph_facts,
            "synthesis_len": len(result.synthesis),
            "synthesis_snippet": result.synthesis[:200] if result.synthesis else "",
            "error": None,
        }
    except Exception as exc:
        latency_ms = (time.perf_counter() - t0) * 1000
        log.error("Agent run failed for query: %s — %s", query_text[:60], exc)
        return {
            "found": False,
            "latency_ms": round(latency_ms, 1),
            "vector_hits": 0,
            "graph_facts": 0,
            "synthesis_len": 0,
            "synthesis_snippet": "",
            "error": str(exc),
        }


def evaluate(
    queries_path: Path,
    output_path: Path,
    config_path: Path,
) -> dict[str, Any]:
    _add_reasoning_to_path()

    # Late import — requires agentic-reasoning on path
    try:
        from src.agent import Agent  # type: ignore[import]
        from src.config import load_config  # type: ignore[import]
    except ImportError as exc:
        log.error(
            "Cannot import agentic-reasoning. "
            "Ensure BENCH_PYTHON points to the reasoning venv: %s", exc
        )
        sys.exit(1)

    # Load golden queries
    with open(queries_path) as f:
        golden = json.load(f)

    queries: list[dict] = golden.get("queries", golden) if isinstance(golden, dict) else golden
    log.info("Loaded %d golden queries from %s", len(queries), queries_path)

    # Build agent from config
    log.info("Loading agent config from %s", config_path)
    try:
        config = load_config(config_path)
        agent = Agent(config)
        model = config.model
    except Exception as exc:
        log.error("Failed to build agent: %s", exc)
        sys.exit(1)

    log.info("Agent ready — model=%s, graphrag collection=%s", model, config.graphrag.collection)

    # Run all queries
    per_query: list[dict[str, Any]] = []
    for q in queries:
        qid = q.get("id", f"q{len(per_query)+1:02d}")
        text = q.get("text", "")
        log.info("[%s] %s", qid, text[:80])

        qr = _run_query(agent, text)
        qr["query_id"] = qid
        qr["query_text"] = text
        per_query.append(qr)

        status = "✓ found" if qr["found"] else "✗ not found"
        log.info(
            "[%s] %s — %.0fms, %d vector hits, %d graph facts",
            qid, status, qr["latency_ms"], qr["vector_hits"], qr["graph_facts"],
        )

    # Aggregate
    total = len(per_query)
    found_count = sum(1 for q in per_query if q["found"])
    found_rate = found_count / total if total > 0 else 0.0

    latencies = [q["latency_ms"] for q in per_query]
    vector_hits = [q["vector_hits"] for q in per_query]
    graph_facts = [q["graph_facts"] for q in per_query]
    synth_lens = [q["synthesis_len"] for q in per_query]
    errors = [q for q in per_query if q["error"]]

    run_id = os.environ.get(_RUN_ID_ENV, f"reasoning_{int(time.time())}")
    timestamp = datetime.now(timezone.utc).isoformat()

    result: dict[str, Any] = {
        "run_id": run_id,
        "timestamp": timestamp,
        "config": {
            "model": model,
            "graphrag_collection": config.graphrag.collection,
            "queries_count": total,
        },
        "aggregate": {
            "found_count": found_count,
            "found_rate": round(found_rate, 4),
            "failure_count": len(errors),
            "latency_ms": _percentiles(latencies),
            "mean_vector_hits": round(float(np.mean(vector_hits)), 2) if vector_hits else 0.0,
            "mean_graph_facts": round(float(np.mean(graph_facts)), 2) if graph_facts else 0.0,
            "mean_synthesis_len": round(float(np.mean(synth_lens)), 1) if synth_lens else 0.0,
        },
        "per_query": per_query,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)
    log.info("Reasoning evaluation written → %s", output_path)

    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run golden queries through the two-phase agent pipeline."
    )
    parser.add_argument(
        "--queries",
        type=Path,
        default=_BENCHMARKING_DIR / "golden" / "queries.json",
        help="Path to golden queries JSON",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output path for reasoning.json",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=_REPO_ROOT / "config" / "app.yaml",
        help="Path to app.yaml",
    )
    args = parser.parse_args()

    result = evaluate(
        queries_path=args.queries,
        output_path=args.output,
        config_path=args.config,
    )

    agg = result["aggregate"]
    print(f"\n── Reasoning Evaluation ─────────────────────────────────────")
    print(f"  Found rate          {agg['found_rate']:.1%}  ({agg['found_count']}/{result['config']['queries_count']})")
    print(f"  Failures            {agg['failure_count']}")
    print(f"  Latency p50         {agg['latency_ms']['p50']:.0f}ms")
    print(f"  Latency p95         {agg['latency_ms']['p95']:.0f}ms")
    print(f"  Mean vector hits    {agg['mean_vector_hits']:.1f}")
    print(f"  Mean graph facts    {agg['mean_graph_facts']:.1f}")
    print(f"  Mean synthesis len  {agg['mean_synthesis_len']:.0f} chars")
    print()


if __name__ == "__main__":
    main()
