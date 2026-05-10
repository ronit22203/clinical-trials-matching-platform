"""
reporter.py — Generates BENCHMARK_<date>.md from a completed run directory.

Aggregates manifest.json, retrieval.json, extraction.json, inference.json
into a reproducible, human-readable Markdown report.

Usage:
    python reporter.py --run-dir results/<RUN_DIR> [--output report.md]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _pct(v: float | None) -> str:
    if v is None:
        return "N/A"
    return f"{v * 100:.1f}%"


def _fmt_ci(m: dict[str, Any]) -> str:
    lo = m.get("ci", {}).get("lower")
    hi = m.get("ci", {}).get("upper")
    v = m.get("value")
    if lo is None or hi is None:
        return _pct(v)
    return f"{_pct(v)} [{_pct(lo)}–{_pct(hi)}]"


def _ms(v: float | None) -> str:
    if v is None:
        return "N/A"
    return f"{v:.1f}"


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def generate_report(run_dir: Path) -> str:
    manifest = _read_json(run_dir / "manifest.json")
    retrieval = _read_json(run_dir / "retrieval.json")
    extraction = _read_json(run_dir / "extraction.json")
    inference = _read_json(run_dir / "inference.json")
    reasoning = _read_json(run_dir / "reasoning.json")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    git_commit = (manifest or {}).get("git_commit", "unknown")[:8]
    git_dirty = (manifest or {}).get("git_dirty", False)
    run_id = (manifest or {}).get("run_id", run_dir.name)
    ts = (manifest or {}).get("timestamp", now)

    lines: list[str] = []
    lines.append("# Healthcare Platform — Benchmark Report")
    lines.append("")
    lines.append(f"**Run ID:** `{run_id}`  ")
    lines.append(f"**Date:** {ts}  ")
    lines.append(f"**Commit:** `{git_commit}`{' *(dirty)*' if git_dirty else ''}  ")
    lines.append(f"**Generated:** {now}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ── Provenance ──────────────────────────────────────────────────────────
    if manifest:
        lines.append("## Provenance")
        lines.append("")
        models = manifest.get("models", {})
        lines.append(f"| Component | Value |")
        lines.append(f"|-----------|-------|")
        lines.append(f"| Embedding model | `{models.get('embedding', 'N/A')}` |")
        lines.append(f"| KG extraction model | `{models.get('kg_extraction', 'N/A')}` |")
        lines.append(f"| Agent reasoning model | `{models.get('agent_reasoning', 'N/A')}` |")

        input_data = manifest.get("input_data", {})
        lines.append(f"| PDF | `{input_data.get('pdf_file', 'N/A')}` |")
        lines.append(f"| PDF SHA-256 | `{(input_data.get('pdf_sha256') or 'N/A')[:20]}…` |")
        lines.append(f"| Chunks file | `{input_data.get('chunks_file', 'N/A')}` |")
        lines.append(f"| Chunk count | {input_data.get('chunks_count', 'N/A')} |")
        lines.append(f"| Qdrant collection | `{input_data.get('qdrant_collection', 'N/A')}` |")
        lines.append(f"| Qdrant points | {input_data.get('qdrant_points', 'N/A')} |")

        cfg_hashes = manifest.get("config_files", {})
        if cfg_hashes:
            lines.append("")
            lines.append("**Config hashes:**")
            for k, v in cfg_hashes.items():
                lines.append(f"- `{k}`: `{str(v)[:28]}…`")

        lines.append("")
        lines.append("---")
        lines.append("")

    # ── Retrieval ────────────────────────────────────────────────────────────
    if retrieval:
        agg = retrieval.get("aggregate", {})
        per_q = retrieval.get("per_query", [])
        cfg = retrieval.get("config", {})
        reranker = cfg.get("reranker_model")

        section_title = "## Retrieval Quality" + (" (reranked)" if reranker else "")
        lines.append(section_title)
        lines.append("")
        retrieval_k_note = (
            f", retrieval_k={cfg.get('retrieval_k', '?')}"
            if reranker else ""
        )
        lines.append(
            f"20 queries, top-{cfg.get('top_k', '?')}{retrieval_k_note}, "
            f"bootstrap n={cfg.get('bootstrap_resamples', '?')}, "
            f"collection `{cfg.get('collection', '?')}`"
        )
        if reranker:
            lines.append(f"reranker `{reranker}`")
        lines.append("")
        lines.append("| Metric | Value | 95% CI |")
        lines.append("|--------|-------|--------|")

        metric_rows = [
            ("Recall@1",    agg.get("recall_at_1", {})),
            ("Recall@3",    agg.get("recall_at_3", {})),
            ("Recall@5",    agg.get("recall_at_5", {})),
            ("Recall@10",   agg.get("recall_at_10", {})),
            ("Precision@5", agg.get("precision_at_5", {})),
            ("NDCG@5",      agg.get("ndcg_at_5", {})),
            ("MRR",         agg.get("mrr", {})),
            ("HitRate@5",   agg.get("hit_rate_at_5", {})),
        ]
        for name, m in metric_rows:
            v = _pct(m.get("value"))
            ci_lo = _pct(m.get("ci", {}).get("lower"))
            ci_hi = _pct(m.get("ci", {}).get("upper"))
            lines.append(f"| {name} | {v} | {ci_lo}–{ci_hi} |")

        lines.append("")

        # Per-query breakdown
        if per_q:
            lines.append("### Per-Query Breakdown")
            lines.append("")
            lines.append("| ID | Category | R@5 | P@5 | NDCG@5 | RR | Top Chunk |")
            lines.append("|----|----------|-----|-----|--------|----|-----------|")
            for q in per_q:
                top_chunk = ""
                if q.get("retrieved_chunks"):
                    top = q["retrieved_chunks"][0]
                    g = top.get("relevance_grade", 0)
                    mark = "✓" if g > 0 else "✗"
                    top_chunk = f"chunk_{top.get('chunk_index', '?'):02d} {mark}"
                lines.append(
                    f"| {q['query_id']} | {q['category']} "
                    f"| {_pct(q.get('recall_at_5'))} "
                    f"| {_pct(q.get('precision_at_5'))} "
                    f"| {_pct(q.get('ndcg_at_5'))} "
                    f"| {_pct(q.get('rr'))} "
                    f"| {top_chunk} |"
                )
        lines.append("")
        lines.append("---")
        lines.append("")

    # ── Extraction ───────────────────────────────────────────────────────────
    if extraction:
        em = extraction.get("entity_metrics", {})
        rm = extraction.get("relation_metrics", {})

        lines.append("## Extraction Quality (1 document)")
        lines.append("")
        lines.append(
            f"Predicted entities: **{extraction.get('predicted_entity_count', 'N/A')}** "
            f"(golden: {extraction.get('golden_entity_count', 'N/A')})  "
        )
        lines.append(
            f"Predicted relations: **{extraction.get('predicted_relation_count', 'N/A')}** "
            f"(golden: {extraction.get('golden_relation_count', 'N/A')})"
        )
        lines.append("")
        lines.append("| Metric | Precision | Recall | F1 |")
        lines.append("|--------|-----------|--------|----|")
        ee = em.get("exact", {})
        er = em.get("relaxed", {})
        rs = rm.get("strict", {})
        rr = rm.get("relaxed", {})
        lines.append(f"| Entity (exact)   | {_pct(ee.get('precision'))} | {_pct(ee.get('recall'))} | {_pct(ee.get('f1'))} |")
        lines.append(f"| Entity (relaxed) | {_pct(er.get('precision'))} | {_pct(er.get('recall'))} | {_pct(er.get('f1'))} |")
        lines.append(f"| Relation (strict) | {_pct(rs.get('precision'))} | {_pct(rs.get('recall'))} | {_pct(rs.get('f1'))} |")
        lines.append(f"| Relation (relaxed)| {_pct(rr.get('precision'))} | {_pct(rr.get('recall'))} | {_pct(rr.get('f1'))} |")
        lines.append("")

        missed = em.get("missed", [])
        if missed:
            lines.append(f"**Missed entities:** {', '.join(f'`{e}`' for e in missed[:10])}" +
                         (" …" if len(missed) > 10 else ""))
            lines.append("")

        lines.append("---")
        lines.append("")

    # ── Inference ────────────────────────────────────────────────────────────
    if inference:
        t = inference.get("ttft_ms", {})
        tp = inference.get("tpot_ms", {})
        th = inference.get("throughput_toks_per_sec", {})
        cfg = inference.get("config", {})

        lines.append("## Inference Performance")
        lines.append("")
        lines.append(
            f"{inference.get('queries_per_run', '?')} queries × "
            f"{inference.get('num_runs', '?')} runs, "
            f"model `{cfg.get('model', '?')}`, "
            f"temp=0, seed=42, max_tokens={cfg.get('max_tokens', '?')}"
        )
        lines.append("")
        lines.append("| Metric | p50 | p95 | p99 | mean | std |")
        lines.append("|--------|-----|-----|-----|------|-----|")
        lines.append(
            f"| TTFT (ms) | {_ms(t.get('p50'))} | {_ms(t.get('p95'))} | {_ms(t.get('p99'))} "
            f"| {_ms(t.get('mean'))} | {_ms(t.get('std'))} |"
        )
        lines.append(
            f"| TPOT (ms) | {_ms(tp.get('p50'))} | {_ms(tp.get('p95'))} | {_ms(tp.get('p99'))} "
            f"| {_ms(tp.get('mean'))} | {_ms(tp.get('std'))} |"
        )
        lines.append(
            f"| Throughput (tok/s) | — | — | — "
            f"| {_ms(th.get('mean'))} | {_ms(th.get('std'))} |"
        )
        lines.append(
            f"| Failures | — | — | — "
            f"| {inference.get('failure_count', 'N/A')}/{inference.get('total_calls', '?')} | — |"
        )
        lines.append("")

        per_run = inference.get("per_run_summary", [])
        if per_run:
            lines.append("**Per-run summary:**")
            lines.append("")
            lines.append("| Run | Successful | Mean TTFT (ms) | Mean Throughput (tok/s) |")
            lines.append("|-----|------------|----------------|------------------------|")
            for r in per_run:
                lines.append(
                    f"| {r['run']} | {r['successful']}/{inference.get('queries_per_run', '?')} "
                    f"| {_ms(r.get('mean_ttft_ms'))} "
                    f"| {_ms(r.get('mean_throughput'))} |"
                )
        lines.append("")
        lines.append("---")
        lines.append("")

    # ── Agent Reasoning ───────────────────────────────────────────────────────
    if reasoning:
        agg = reasoning.get("aggregate", {})
        rcfg = reasoning.get("config", {})
        latency = agg.get("latency_ms", {})
        per_query = reasoning.get("per_query", [])

        lines.append("## Agent Reasoning")
        lines.append("")
        lines.append(
            f"{rcfg.get('queries_count', '?')} queries, "
            f"model `{rcfg.get('model', '?')}`, "
            f"collection `{rcfg.get('graphrag_collection', '?')}`"
        )
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        lines.append(f"| Found rate | {_pct(agg.get('found_rate'))} ({agg.get('found_count', 'N/A')}/{rcfg.get('queries_count', '?')}) |")
        lines.append(f"| Failures | {agg.get('failure_count', 0)} |")
        lines.append(f"| Latency p50 | {_ms(latency.get('p50'))} ms |")
        lines.append(f"| Latency p95 | {_ms(latency.get('p95'))} ms |")
        lines.append(f"| Latency mean | {_ms(latency.get('mean'))} ms |")
        lines.append(f"| Mean vector hits | {agg.get('mean_vector_hits', 'N/A')} |")
        lines.append(f"| Mean graph facts | {agg.get('mean_graph_facts', 'N/A')} |")
        lines.append(f"| Mean synthesis length | {agg.get('mean_synthesis_len', 'N/A')} chars |")
        lines.append("")

        if per_query:
            lines.append("**Per-query breakdown:**")
            lines.append("")
            lines.append("| ID | Found | Latency (ms) | Vector Hits | Graph Facts | Synthesis (snippet) |")
            lines.append("|----|-------|-------------|-------------|-------------|---------------------|")
            for q in per_query[:20]:  # cap at 20 rows
                found_icon = "✓" if q.get("found") else "✗"
                snippet = (q.get("synthesis_snippet") or "")[:60].replace("|", "\\|")
                lines.append(
                    f"| `{q.get('query_id', '?')}` "
                    f"| {found_icon} "
                    f"| {_ms(q.get('latency_ms'))} "
                    f"| {q.get('vector_hits', 0)} "
                    f"| {q.get('graph_facts', 0)} "
                    f"| {snippet}… |"
                )
            lines.append("")

        lines.append("---")
        lines.append("")

    # ── Reproduce ────────────────────────────────────────────────────────────
    lines.append("## Reproduce")
    lines.append("")
    lines.append("```bash")
    lines.append("git clone <repo> && cd healthcare-platform")
    if git_commit and git_commit != "unknown":
        lines.append(f"git checkout {git_commit}")
    lines.append("make bootstrap && make up")
    lines.append("make benchmark-all")
    lines.append("```")
    lines.append("")

    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser(description="Generate benchmark Markdown report")
    p.add_argument("--run-dir", required=True, help="Path to run directory")
    p.add_argument("--output", default=None, help="Output path (default: <run-dir>/report.md)")
    args = p.parse_args()

    run_dir = Path(args.run_dir)
    if not run_dir.exists():
        print(f"ERROR: run-dir not found: {run_dir}", file=sys.stderr)
        sys.exit(1)

    output_path = Path(args.output) if args.output else run_dir / "report.md"
    report = generate_report(run_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write(report)
    print(f"Report written → {output_path}")


if __name__ == "__main__":
    main()
