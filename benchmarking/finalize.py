"""
finalize.py — Merge all deterministic-run stage outputs into a single manifest.json.

Reads from run_dir:
  manifest.json         - provenance snapshot (written by provenance.py)
  pipeline_ingest.json  - ingest stage elapsed time
  pipeline_graph.json   - graph build elapsed time
  retrieval.json        - Recall@K, NDCG, MRR, HitRate + bootstrap CIs
  extraction.json       - entity/relation F1 (exact + relaxed)
  inference.json        - TTFT, TPOT, throughput across N runs

Writes:
  manifest.json         - merged complete manifest (overwrites provenance snapshot)

The final manifest is the single source of truth for a deterministic run:
provenance + pipeline timings + benchmark metrics + headline summary,
all in one JSON.
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def _safe_load(path: Path) -> dict[str, Any]:
    """Load JSON; return {} on missing file or parse error."""
    if not path.exists():
        log.warning("Missing stage output: %s", path.name)
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        log.error("Cannot read %s: %s", path.name, exc)
        return {}


def _val(d: dict[str, Any], *keys: str) -> float | None:
    """Safely traverse a nested dict and coerce the leaf to float."""
    node: Any = d
    for k in keys:
        if not isinstance(node, dict) or k not in node:
            return None
        node = node[k]
    try:
        return float(node)
    except (TypeError, ValueError):
        return None


def _build_summary(
    retrieval: dict[str, Any],
    extraction: dict[str, Any],
    inference: dict[str, Any],
) -> dict[str, Any]:
    """Headline metrics — the numbers that go on the cover page of a report."""
    agg  = retrieval.get("aggregate", {})
    ent  = extraction.get("entity_metrics", {})
    rel  = extraction.get("relation_metrics", {})
    ttft = inference.get("ttft_ms", {})
    tp   = inference.get("throughput_toks_per_sec", {})

    failure_rate: float | None = None
    if inference.get("total_calls", 0) > 0:
        failure_rate = round(
            inference.get("failure_count", 0) / inference["total_calls"], 4
        )

    raw: dict[str, float | None] = {
        # --- Retrieval ---
        "recall_at_1":          _val(agg, "recall_at_1",  "value"),
        "recall_at_5":          _val(agg, "recall_at_5",  "value"),
        "recall_at_5_ci_low":   _val(agg, "recall_at_5",  "ci", "low"),
        "recall_at_5_ci_high":  _val(agg, "recall_at_5",  "ci", "high"),
        "ndcg_at_5":            _val(agg, "ndcg_at_5",    "value"),
        "mrr":                  _val(agg, "mrr",           "value"),
        "hit_rate_at_5":        _val(agg, "hit_rate_at_5", "value"),
        # --- Extraction ---
        "entity_f1_exact":      _val(ent, "exact",   "f1"),
        "entity_f1_relaxed":    _val(ent, "relaxed", "f1"),
        "relation_f1_strict":   _val(rel, "strict",  "f1"),
        "relation_f1_relaxed":  _val(rel, "relaxed", "f1"),
        # --- Inference ---
        "ttft_p50_ms":          _val(ttft, "p50"),
        "ttft_p95_ms":          _val(ttft, "p95"),
        "throughput_tok_s":     _val(tp,   "mean"),
        "failure_rate":         failure_rate,
    }
    # Drop None entries so missing stages don't pollute the summary block
    return {k: v for k, v in raw.items() if v is not None}


def finalize(run_dir: Path) -> dict[str, Any]:
    """
    Merge stage outputs into manifest.json.

    Returns the complete manifest dict.
    """
    manifest   = _safe_load(run_dir / "manifest.json")
    retrieval  = _safe_load(run_dir / "retrieval.json")
    extraction = _safe_load(run_dir / "extraction.json")
    inference  = _safe_load(run_dir / "inference.json")

    # Collect all pipeline_*.json timing files in stage order
    pipeline: dict[str, Any] = {}
    for timing_file in sorted(run_dir.glob("pipeline_*.json")):
        data = _safe_load(timing_file)
        stage = data.get("stage", timing_file.stem.removeprefix("pipeline_"))
        pipeline[stage] = data

    summary = _build_summary(retrieval, extraction, inference)

    manifest.update({
        "run_type": "deterministic",
        "pipeline": pipeline,
        "benchmark": {
            "retrieval":  retrieval,
            "extraction": extraction,
            "inference":  inference,
        },
        "summary": summary,
    })

    out_path = run_dir / "manifest.json"
    with open(out_path, "w") as f:
        json.dump(manifest, f, indent=2)

    log.info("Manifest finalized → %s", out_path)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Merge deterministic-run stage outputs into manifest.json.",
    )
    parser.add_argument("--run-dir", required=True, type=Path, help="Path to run directory")
    args = parser.parse_args()

    result = finalize(args.run_dir.resolve())
    summary = result.get("summary", {})

    print("\n── Deterministic Run Summary ────────────────────────────")
    w = max((len(k) for k in summary), default=28)
    for key, val in summary.items():
        formatted = f"{val:.4f}" if isinstance(val, float) else str(val)
        print(f"  {key:<{w}}  {formatted}")
    print()


if __name__ == "__main__":
    main()
