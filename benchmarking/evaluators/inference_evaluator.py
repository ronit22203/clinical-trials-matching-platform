"""
inference_evaluator.py — TTFT, TPOT, throughput via LM Studio streaming API.

Makes 3 independent runs of the 20 golden queries through the chat completions
endpoint with streaming enabled, capturing:
  - TTFT  (ms): time from request sent to first token received
  - TPOT  (ms): average time per output token
  - Throughput (tok/s): mean over all successful calls
  - Failure count

Usage:
    python evaluators/inference_evaluator.py \\
        --queries golden/queries.json \\
        --output results/<RUN_DIR>/inference.json \\
        --runs 3 \\
        [--model qwen3-8b] \\
        [--base-url http://localhost:1234/v1] \\
        [--max-tokens 256] \\
        [--timeout 120]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
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
_RUN_ID_ENV = "BENCH_RUN_ID"

# System prompt used for inference benchmarking — concise to keep responses short
_SYSTEM_PROMPT = (
    "You are a clinical research assistant. Answer the question concisely "
    "based on your training data. Keep answers under 3 sentences."
)


# ---------------------------------------------------------------------------
# Helpers
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


def _percentiles(data: list[float]) -> dict[str, float]:
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


# ---------------------------------------------------------------------------
# Streaming inference call
# ---------------------------------------------------------------------------

def _call_streaming(
    base_url: str,
    model: str,
    query: str,
    max_tokens: int,
    timeout: int,
) -> dict[str, Any]:
    """
    Call the OpenAI-compatible streaming API and measure TTFT + TPOT.

    Returns dict with:
      ttft_ms, tpot_ms, total_ms, tokens_out, throughput_toks_per_sec, success, error
    """
    import urllib.request
    import urllib.error

    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": query},
        ],
        "max_tokens": max_tokens,
        "stream": True,
        "temperature": 0.0,  # deterministic
        "seed": 42,
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    t_start = time.perf_counter()
    ttft_ms: float | None = None
    tokens_out = 0

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            for raw_line in resp:
                line = raw_line.decode("utf-8").strip()
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                delta = chunk.get("choices", [{}])[0].get("delta", {})
                content = delta.get("content", "")
                if content:
                    if ttft_ms is None:
                        ttft_ms = (time.perf_counter() - t_start) * 1000
                    # Rough token count: space-separated words as proxy (no tiktoken dep)
                    tokens_out += max(1, len(content.split()))

        t_end = time.perf_counter()
        total_ms = (t_end - t_start) * 1000

        # TPOT = (total_time - TTFT) / tokens_out, but guard against 0
        if tokens_out > 1 and ttft_ms is not None:
            tpot_ms = (total_ms - ttft_ms) / (tokens_out - 1)
        else:
            tpot_ms = total_ms / max(tokens_out, 1)

        throughput = (tokens_out / (total_ms / 1000)) if total_ms > 0 else 0.0

        return {
            "ttft_ms": ttft_ms or total_ms,
            "tpot_ms": max(tpot_ms, 0.0),
            "total_ms": total_ms,
            "tokens_out": tokens_out,
            "throughput_toks_per_sec": throughput,
            "success": True,
            "error": None,
        }

    except Exception as exc:
        t_end = time.perf_counter()
        return {
            "ttft_ms": None,
            "tpot_ms": None,
            "total_ms": (t_end - t_start) * 1000,
            "tokens_out": 0,
            "throughput_toks_per_sec": 0.0,
            "success": False,
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------

class InferenceEvaluator:
    def __init__(
        self,
        base_url: str,
        model: str,
        max_tokens: int = 256,
        timeout: int = 120,
        num_runs: int = 3,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.num_runs = num_runs

    def run(self, queries_path: Path, output_path: Path, run_id: str) -> dict[str, Any]:
        with open(queries_path) as f:
            queries_data = json.load(f)

        queries = [q["text"] for q in queries_data["queries"]]
        total_calls = self.num_runs * len(queries)
        log.info(
            "Inference benchmark: %d queries × %d runs = %d calls → %s",
            len(queries), self.num_runs, total_calls, self.model,
        )

        all_results: list[dict[str, Any]] = []
        run_details: list[list[dict[str, Any]]] = []
        failure_count = 0

        for run_idx in range(self.num_runs):
            log.info("  Run %d/%d …", run_idx + 1, self.num_runs)
            run_calls: list[dict[str, Any]] = []
            for q_idx, query in enumerate(queries):
                log.debug("    [%d/%d] %s", q_idx + 1, len(queries), query[:60])
                res = _call_streaming(
                    self.base_url, self.model, query,
                    self.max_tokens, self.timeout,
                )
                res["run"] = run_idx + 1
                res["query_index"] = q_idx
                run_calls.append(res)
                all_results.append(res)
                if not res["success"]:
                    failure_count += 1
                    log.warning("    FAILED: %s", res["error"])

            run_details.append(run_calls)

        successful = [r for r in all_results if r["success"]]
        ttft_vals = [r["ttft_ms"] for r in successful if r["ttft_ms"] is not None]
        tpot_vals = [r["tpot_ms"] for r in successful if r["tpot_ms"] is not None]
        throughput_vals = [r["throughput_toks_per_sec"] for r in successful]

        ttft_stats = _percentiles(ttft_vals) if ttft_vals else {}
        tpot_stats = _percentiles(tpot_vals) if tpot_vals else {}

        result: dict[str, Any] = {
            "run_id": run_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "config": {
                "model": self.model,
                "base_url": self.base_url,
                "max_tokens": self.max_tokens,
                "temperature": 0.0,
                "seed": 42,
            },
            "num_runs": self.num_runs,
            "queries_per_run": len(queries),
            "total_calls": total_calls,
            "successful_calls": len(successful),
            "failure_count": failure_count,
            "ttft_ms": ttft_stats,
            "tpot_ms": tpot_stats,
            "throughput_toks_per_sec": {
                "mean": float(np.mean(throughput_vals)) if throughput_vals else 0.0,
                "std": float(np.std(throughput_vals)) if throughput_vals else 0.0,
                "min": float(np.min(throughput_vals)) if throughput_vals else 0.0,
                "max": float(np.max(throughput_vals)) if throughput_vals else 0.0,
            },
            "per_run_summary": [
                {
                    "run": idx + 1,
                    "successful": sum(1 for r in run_calls if r["success"]),
                    "mean_ttft_ms": float(np.mean([r["ttft_ms"] for r in run_calls if r["success"] and r["ttft_ms"]])) if any(r["success"] for r in run_calls) else None,
                    "mean_throughput": float(np.mean([r["throughput_toks_per_sec"] for r in run_calls if r["success"]])) if any(r["success"] for r in run_calls) else None,
                }
                for idx, run_calls in enumerate(run_details)
            ],
        }

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(result, f, indent=2)

        log.info("Inference results written → %s", output_path)
        _print_summary(result)
        return result


def _print_summary(result: dict[str, Any]) -> None:
    print("\n── Inference Summary ────────────────────────────────")
    print(f"  Model:    {result['config']['model']}")
    print(f"  Calls:    {result['successful_calls']}/{result['total_calls']} succeeded")
    print(f"  Failures: {result['failure_count']}")

    if result["ttft_ms"]:
        t = result["ttft_ms"]
        print(f"\n  TTFT (ms)  p50={t.get('p50',0):.1f}  p95={t.get('p95',0):.1f}  p99={t.get('p99',0):.1f}")
    if result["tpot_ms"]:
        t = result["tpot_ms"]
        print(f"  TPOT (ms)  p50={t.get('p50',0):.2f}  p95={t.get('p95',0):.2f}  p99={t.get('p99',0):.2f}")
    th = result["throughput_toks_per_sec"]
    print(f"  Throughput mean={th['mean']:.1f} tok/s  std={th['std']:.1f}")
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Inference evaluator: TTFT/TPOT/throughput")
    p.add_argument("--queries", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--run-id", default=os.environ.get(_RUN_ID_ENV, f"bench_{int(time.time())}"))
    p.add_argument("--model", default=None)
    p.add_argument("--base-url", default=None)
    p.add_argument("--max-tokens", type=int, default=256)
    p.add_argument("--timeout", type=int, default=120)
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

    ar_cfg = app_cfg.get("agentic_reasoning", {})
    agents = ar_cfg.get("agents", {})
    default_model = "unknown"
    default_url = "http://localhost:1234/v1"

    if agents:
        first_agent = next(iter(agents.values()))
        default_model = first_agent.get("model", "unknown")

    # Try to get base_url from first agent's LLM config
    llm_configs = ar_cfg.get("llm_configs", {})
    if llm_configs:
        first_llm = next(iter(llm_configs.values()))
        raw_url = first_llm.get("base_url", default_url)
        default_url = _resolve(raw_url)

    # Fallback to env var
    if "LM_STUDIO_BASE_URL" in env:
        default_url = env["LM_STUDIO_BASE_URL"]

    evaluator = InferenceEvaluator(
        base_url=args.base_url or default_url,
        model=args.model or default_model,
        max_tokens=args.max_tokens,
        timeout=args.timeout,
        num_runs=args.runs,
    )
    evaluator.run(
        queries_path=Path(args.queries),
        output_path=Path(args.output),
        run_id=args.run_id,
    )


if __name__ == "__main__":
    main()
