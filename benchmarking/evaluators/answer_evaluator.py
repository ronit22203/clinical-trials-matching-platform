"""
answer_evaluator.py — Grade local agent answers against the OpenAI answer key.

Reads golden/golden_answers.json and a run's reasoning.json (full synthesis),
then asks gpt-6.1-sol to score correctness, factual depth, and entity coverage.

If the answer key or OPENAI_API_KEY is missing, writes a skipped result and
exits 0 so a local-only deterministic run can still finish.

Usage:
    python evaluators/answer_evaluator.py \\
        --golden golden/golden_answers.json \\
        --reasoning results/<RUN_DIR>/reasoning.json \\
        --output results/<RUN_DIR>/answer_quality.json
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai_client import complete_text, load_env, parse_json_object, resolve_api_key, resolve_model

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

_RUN_ID_ENV = "BENCH_RUN_ID"

_INSTRUCTIONS = """You grade a local clinical QA answer against a reference answer.
Score only how well the candidate matches the reference. Do not reward claims
that the reference does not support.
Return a JSON object with exactly these keys:
  "correctness": integer 1-5. 5 means the candidate's claims match the reference and do not contradict it.
  "factual_depth": integer 1-5. 5 means the candidate covers the reference's material facts.
  "entity_coverage": integer 1-5. 5 means the candidate names the same clinical entities as the reference.
  "missing_facts": array of short strings for important reference facts the candidate omitted
  "unsupported_claims": array of short strings for candidate claims the reference does not support
"""


def _clamp_score(value: Any) -> int:
    try:
        score = int(round(float(value)))
    except (TypeError, ValueError):
        return 1
    return max(1, min(5, score))


def _string_list(value: Any, limit: int = 8) -> list[str]:
    if not isinstance(value, list):
        return []
    items = [str(item).strip() for item in value if str(item).strip()]
    return items[:limit]


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 4)


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


def _skipped(output_path: Path, run_id: str, reason: str) -> dict[str, Any]:
    payload = {
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "skipped": True,
        "reason": reason,
    }
    _write(output_path, payload)
    log.warning("Answer judge skipped: %s", reason)
    return payload


def _grade_one(
    api_key: str,
    model: str,
    question: str,
    reference: str,
    candidate: str,
) -> dict[str, Any]:
    raw = complete_text(
        api_key=api_key,
        model=model,
        instructions=_INSTRUCTIONS,
        user_text=(
            f"QUESTION:\n{question}\n\n"
            f"REFERENCE:\n{reference}\n\n"
            f"CANDIDATE:\n{candidate or '[no answer]'}"
        ),
        json_mode=True,
    )
    parsed = parse_json_object(raw)
    correctness = _clamp_score(parsed.get("correctness"))
    factual_depth = _clamp_score(parsed.get("factual_depth"))
    entity_coverage = _clamp_score(parsed.get("entity_coverage"))
    return {
        "correctness": correctness,
        "factual_depth": factual_depth,
        "entity_coverage": entity_coverage,
        "overall": round((correctness + factual_depth + entity_coverage) / 3, 4),
        "missing_facts": _string_list(parsed.get("missing_facts")),
        "unsupported_claims": _string_list(parsed.get("unsupported_claims")),
    }


def evaluate(
    golden_path: Path,
    reasoning_path: Path,
    output_path: Path,
    run_id: str,
) -> dict[str, Any]:
    if not golden_path.is_file():
        return _skipped(
            output_path,
            run_id,
            f"golden answers not found at {golden_path}. Run make golden-answers first.",
        )

    env = load_env()
    api_key = resolve_api_key(env)
    if not api_key:
        return _skipped(
            output_path,
            run_id,
            "OPENAI_API_KEY is missing. Add it to .env.local to enable answer judging.",
        )
    model = resolve_model(env)

    if not reasoning_path.is_file():
        log.error("reasoning.json not found: %s", reasoning_path)
        raise SystemExit(1)

    with open(golden_path) as handle:
        golden = json.load(handle)
    with open(reasoning_path) as handle:
        reasoning = json.load(handle)

    references = {
        item["id"]: item
        for item in golden.get("answers", [])
        if isinstance(item, dict) and item.get("id")
    }
    local_by_id = {
        item.get("query_id"): item
        for item in reasoning.get("per_query", [])
        if isinstance(item, dict)
    }
    if not references:
        return _skipped(output_path, run_id, f"{golden_path} contains no answers.")

    per_query: list[dict[str, Any]] = []
    for query_id, reference in references.items():
        local = local_by_id.get(query_id, {})
        candidate = local.get("synthesis") or local.get("synthesis_snippet") or ""
        question = reference.get("query") or local.get("query_text") or ""
        log.info("[%s] judging", query_id)
        graded = _grade_one(
            api_key,
            model,
            question,
            reference.get("answer", ""),
            candidate,
        )
        per_query.append({
            "query_id": query_id,
            "question": question,
            **graded,
        })
        log.info(
            "[%s] correctness=%d depth=%d entities=%d",
            query_id,
            graded["correctness"],
            graded["factual_depth"],
            graded["entity_coverage"],
        )

    aggregate = {
        "queries": len(per_query),
        "correctness": _mean([row["correctness"] for row in per_query]),
        "factual_depth": _mean([row["factual_depth"] for row in per_query]),
        "entity_coverage": _mean([row["entity_coverage"] for row in per_query]),
        "overall": _mean([row["overall"] for row in per_query]),
    }
    payload = {
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "skipped": False,
        "config": {
            "model": model,
            "golden_answers": str(golden_path),
            "generator_model": golden.get("generator_model"),
        },
        "aggregate": aggregate,
        "per_query": per_query,
    }
    _write(output_path, payload)
    log.info("Answer quality written → %s", output_path)
    _print_summary(aggregate)
    return payload


def _print_summary(aggregate: dict[str, Any]) -> None:
    print("\n── Answer Quality ───────────────────────────────────────")
    print(f"  Queries             {aggregate['queries']}")
    print(f"  Correctness         {aggregate['correctness']:.2f} / 5")
    print(f"  Factual depth       {aggregate['factual_depth']:.2f} / 5")
    print(f"  Entity coverage     {aggregate['entity_coverage']:.2f} / 5")
    print(f"  Overall             {aggregate['overall']:.2f} / 5")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Judge local answers against golden answers.")
    parser.add_argument("--golden", type=Path, required=True)
    parser.add_argument("--reasoning", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-id", default=os.environ.get(_RUN_ID_ENV, f"bench_{int(time.time())}"))
    args = parser.parse_args()
    evaluate(args.golden, args.reasoning, args.output, args.run_id)


if __name__ == "__main__":
    main()
