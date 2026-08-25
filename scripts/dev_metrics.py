#!/usr/bin/env python3
"""Dump every live platform metric to stdout. Dev / prod-startup use.

Reads .env.local, probes services from docs_v2/prod-startup.md, prints
artifact counts, Qdrant/Neo4j stats, inference health, GPU, and (if present)
every key from the latest benchmarking run.

Usage:
    python3 scripts/dev_metrics.py
    python3 scripts/dev_metrics.py --json
    python3 scripts/dev_metrics.py --run-dir benchmarking/results/<id>
    make metrics
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
TIMEOUT = 3.0

BLUE = "\033[34m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
BOLD = "\033[1m"
DIM = "\033[2m"
NC = "\033[0m"

# Ports from docs_v2/prod-startup.md + Makefile `dev`
SERVICES: list[tuple[str, str, int, str]] = [
    ("Qdrant HTTP", "QDRANT_URL", 6333, "/collections"),
    ("Qdrant gRPC", "", 6334, ""),
    ("Neo4j HTTP", "", 7474, ""),
    ("Neo4j Bolt", "NEO4J_URI", 7687, ""),
    ("SGLang / inference", "SGLANG_BASE_URL", 30000, "/v1/models"),
    ("Ollama", "OLLAMA_BASE_URL", 11434, "/api/tags"),
    ("LM Studio", "LM_STUDIO_BASE_URL", 1234, "/v1/models"),
    ("Reasoning API", "REASONING_API_PORT", 8000, "/api/health"),
    ("Ingestion API", "", 8002, "/docs"),
    ("Blueprint UI (Vite)", "", 5173, ""),
    ("Blueprint preview", "", 4173, ""),
]


def _use_color() -> bool:
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def c(code: str, text: str) -> str:
    if not _use_color():
        return text
    return f"{code}{text}{NC}"


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def _host_port_from_url(url: str, default_port: int) -> tuple[str, int]:
    rest = url.split("://", 1)[-1]
    hostport = rest.split("/", 1)[0]
    if ":" in hostport:
        host, port_s = hostport.rsplit(":", 1)
        try:
            return host, int(port_s)
        except ValueError:
            return host, default_port
    return hostport or "localhost", default_port


def tcp_open(host: str, port: int, timeout: float = TIMEOUT) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def http_json(
    url: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = TIMEOUT,
) -> tuple[int | None, Any]:
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Accept", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            raw = resp.read()
            code = resp.getcode()
        if not raw:
            return code, None
        try:
            return code, json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return code, raw.decode("utf-8", errors="replace")[:200]
    except urllib.error.HTTPError as exc:
        try:
            payload = exc.read().decode("utf-8", errors="replace")
            return exc.code, json.loads(payload)
        except Exception:
            return exc.code, None
    except Exception:
        return None, None


def git_info() -> dict[str, Any]:
    def _run(args: list[str]) -> str:
        try:
            r = subprocess.run(
                args, cwd=REPO_ROOT, capture_output=True, text=True, timeout=5
            )
            return r.stdout.strip() if r.returncode == 0 else ""
        except Exception:
            return ""

    commit = _run(["git", "rev-parse", "--short", "HEAD"]) or "unknown"
    dirty = bool(_run(["git", "status", "--porcelain"]))
    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"]) or "unknown"
    return {"commit": commit, "branch": branch, "dirty": dirty}


def count_files(root: Path, pattern: str) -> int:
    if not root.exists():
        return 0
    return sum(1 for _ in root.rglob(pattern) if _.is_file())


def dir_size_bytes(root: Path) -> int:
    if not root.exists():
        return 0
    total = 0
    for p in root.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return total


def fmt_bytes(n: int) -> str:
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{n} B"


def flatten(obj: Any, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            out.update(flatten(v, key))
    elif isinstance(obj, list):
        if not obj:
            out[prefix or "[]"] = []
        elif all(not isinstance(x, (dict, list)) for x in obj):
            out[prefix] = obj
        else:
            for i, v in enumerate(obj):
                out.update(flatten(v, f"{prefix}[{i}]"))
    else:
        out[prefix] = obj
    return out


def gpu_stats() -> dict[str, Any] | None:
    try:
        r = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.used,memory.total,utilization.gpu,"
                "temperature.gpu,power.draw",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode != 0 or not r.stdout.strip():
            return None
        line = r.stdout.strip().splitlines()[0]
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 6:
            return {"raw": line}
        return {
            "name": parts[0],
            "vram_used_mb": float(parts[1]),
            "vram_total_mb": float(parts[2]),
            "util_pct": float(parts[3]),
            "temp_c": float(parts[4]),
            "power_w": float(parts[5]),
        }
    except Exception:
        return None


def probe_services(env: dict[str, str]) -> list[dict[str, Any]]:
    rows = []
    for name, env_key, default_port, path in SERVICES:
        host, port = "localhost", default_port
        url = env.get(env_key, "") if env_key else ""
        if env_key == "REASONING_API_PORT" and env.get("REASONING_API_PORT"):
            try:
                port = int(env["REASONING_API_PORT"])
            except ValueError:
                pass
        elif url:
            host, port = _host_port_from_url(url, default_port)
        open_ = tcp_open(host, port)
        http_ok = None
        detail = None
        if open_ and path:
            scheme = "http"
            base = f"{scheme}://{host}:{port}{path}"
            code, payload = http_json(base)
            http_ok = code == 200
            if isinstance(payload, dict):
                if "data" in payload and isinstance(payload["data"], list):
                    detail = [m.get("id") for m in payload["data"] if isinstance(m, dict)]
                elif "models" in payload and isinstance(payload["models"], list):
                    detail = [
                        m.get("name") or m.get("model")
                        for m in payload["models"]
                        if isinstance(m, dict)
                    ]
                elif "result" in payload and isinstance(payload["result"], dict):
                    cols = payload["result"].get("collections")
                    if isinstance(cols, list):
                        detail = [
                            c.get("name") for c in cols if isinstance(c, dict)
                        ]
                elif path.endswith("/health"):
                    detail = payload
        rows.append(
            {
                "name": name,
                "host": host,
                "port": port,
                "tcp": open_,
                "http_ok": http_ok,
                "detail": detail,
            }
        )
    return rows


def qdrant_metrics(qdrant_url: str) -> dict[str, Any]:
    base = qdrant_url.rstrip("/")
    code, payload = http_json(f"{base}/collections")
    if code != 200 or not isinstance(payload, dict):
        return {"reachable": False}
    collections = payload.get("result", {}).get("collections") or []
    names = [c.get("name") for c in collections if isinstance(c, dict) and c.get("name")]
    details = []
    for name in names:
        ccode, info = http_json(f"{base}/collections/{name}")
        if ccode != 200 or not isinstance(info, dict):
            details.append({"name": name, "error": True})
            continue
        result = info.get("result") or {}
        config = result.get("config") or {}
        params = config.get("params") or {}
        vectors = params.get("vectors") or {}
        details.append(
            {
                "name": name,
                "status": result.get("status"),
                "points_count": result.get("points_count"),
                "indexed_vectors_count": result.get("indexed_vectors_count"),
                "segments_count": result.get("segments_count"),
                "optimizer_status": result.get("optimizer_status"),
                "vector_size": vectors.get("size") if isinstance(vectors, dict) else None,
                "distance": vectors.get("distance") if isinstance(vectors, dict) else None,
            }
        )
    return {"reachable": True, "collections": details}


def neo4j_metrics(env: dict[str, str]) -> dict[str, Any]:
    user = env.get("NEO4J_USER", "neo4j")
    password = env.get("NEO4J_PASSWORD", "testpassword")
    http_host, http_port = "localhost", 7474
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    headers = {
        "Authorization": f"Basic {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    statements = [
        {"statement": "MATCH (n) RETURN count(n) AS nodes"},
        {"statement": "MATCH ()-[r]->() RETURN count(r) AS rels"},
        {
            "statement": (
                "MATCH (n) UNWIND labels(n) AS label "
                "RETURN label, count(*) AS c ORDER BY c DESC"
            )
        },
        {
            "statement": (
                "MATCH ()-[r]->() RETURN type(r) AS t, count(*) AS c ORDER BY c DESC"
            )
        },
    ]
    body = json.dumps({"statements": statements}).encode()
    urls = [
        f"http://{http_host}:{http_port}/db/neo4j/tx/commit",
        f"http://{http_host}:{http_port}/db/data/transaction/commit",
    ]
    payload = None
    used = None
    for url in urls:
        code, payload = http_json(url, method="POST", body=body, headers=headers)
        if code == 200 and isinstance(payload, dict) and not payload.get("errors"):
            used = url
            break
    if not used or not isinstance(payload, dict):
        return {
            "reachable": tcp_open(http_host, http_port),
            "error": "HTTP Cypher API unavailable (is Neo4j up? credentials in .env.local?)",
        }
    results = payload.get("results") or []

    def _scalar(idx: int, col: str) -> int | None:
        if idx >= len(results):
            return None
        data = results[idx].get("data") or []
        if not data:
            return 0
        row = data[0].get("row") or []
        return int(row[0]) if row else 0

    def _pairs(idx: int) -> list[dict[str, Any]]:
        if idx >= len(results):
            return []
        out = []
        for item in results[idx].get("data") or []:
            row = item.get("row") or []
            if len(row) >= 2:
                out.append({"name": row[0], "count": row[1]})
        return out

    return {
        "reachable": True,
        "endpoint": used,
        "nodes": _scalar(0, "nodes"),
        "relationships": _scalar(1, "rels"),
        "labels": _pairs(2),
        "relationship_types": _pairs(3),
    }


def inference_metrics(env: dict[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    sglang = env.get("SGLANG_BASE_URL", "http://localhost:30000/v1").rstrip("/")
    if sglang.endswith("/v1"):
        sglang_root = sglang[: -len("/v1")]
    else:
        sglang_root = sglang
    code, models = http_json(f"{sglang_root}/v1/models")
    out["sglang"] = {
        "url": sglang_root,
        "reachable": code == 200,
        "models": (
            [m.get("id") for m in (models or {}).get("data", [])]
            if isinstance(models, dict)
            else None
        ),
    }
    cache_code, cache = http_json(f"{sglang_root}/get_cache_stats")
    if cache_code == 200:
        out["sglang"]["cache"] = cache

    ollama = env.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    ocode, otags = http_json(f"{ollama}/api/tags")
    names = []
    if isinstance(otags, dict):
        for m in otags.get("models") or []:
            if isinstance(m, dict):
                names.append(m.get("name"))
    out["ollama"] = {"url": ollama, "reachable": ocode == 200, "models": names}

    lm = env.get("LM_STUDIO_BASE_URL", "http://localhost:1234/v1").rstrip("/")
    lcode, lmodels = http_json(f"{lm}/models" if lm.endswith("/v1") else f"{lm}/v1/models")
    lm_ids = []
    if isinstance(lmodels, dict):
        lm_ids = [m.get("id") for m in lmodels.get("data") or [] if isinstance(m, dict)]
    out["lm_studio"] = {"url": lm, "reachable": lcode == 200, "models": lm_ids}
    return out


def latest_run_dir(explicit: Path | None) -> Path | None:
    if explicit:
        return explicit if explicit.exists() else None
    results = REPO_ROOT / "benchmarking" / "results"
    if not results.exists():
        return None
    dirs = [p for p in results.iterdir() if p.is_dir()]
    if not dirs:
        return None
    return max(dirs, key=lambda p: p.stat().st_mtime)


def benchmark_metrics(run_dir: Path | None) -> dict[str, Any]:
    if run_dir is None:
        return {"present": False}
    files = [
        "manifest.json",
        "retrieval.json",
        "extraction.json",
        "inference.json",
        "reasoning.json",
        "pipeline_ingest.json",
        "pipeline_graph.json",
    ]
    loaded: dict[str, Any] = {"present": True, "run_dir": str(run_dir)}
    for name in files:
        path = run_dir / name
        if not path.exists():
            continue
        try:
            loaded[name.replace(".json", "")] = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            loaded[name.replace(".json", "")] = {"error": "invalid json"}
    return loaded


def collect(run_dir: Path | None) -> dict[str, Any]:
    env = load_env(REPO_ROOT / ".env.local")
    qdrant_url = env.get("QDRANT_URL", "http://localhost:6333")
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git": git_info(),
        "env_file": (REPO_ROOT / ".env.local").exists(),
        "services": probe_services(env),
        "gpu": gpu_stats(),
        "artifacts": {
            "pdfs": count_files(REPO_ROOT / "data" / "pdfs", "*.pdf"),
            "ocr": count_files(REPO_ROOT / "data" / "artifacts" / "extract", "*"),
            "markdown": count_files(REPO_ROOT / "data" / "artifacts" / "convert", "*"),
            "cleaned": count_files(REPO_ROOT / "data" / "artifacts" / "clean", "*"),
            "chunks": count_files(REPO_ROOT / "data" / "artifacts" / "chunk", "*"),
            "chunk_json": count_files(
                REPO_ROOT / "data" / "artifacts" / "chunk", "*_chunks.json"
            ),
            "artifacts_bytes": dir_size_bytes(REPO_ROOT / "data" / "artifacts"),
            "pdfs_bytes": dir_size_bytes(REPO_ROOT / "data" / "pdfs"),
        },
        "qdrant": qdrant_metrics(qdrant_url),
        "neo4j": neo4j_metrics(env),
        "inference": inference_metrics(env),
        "benchmark": benchmark_metrics(run_dir),
    }


def _status_word(ok: bool) -> str:
    return c(GREEN, "up") if ok else c(YELLOW, "down")


def print_human(data: dict[str, Any]) -> None:
    print()
    print(c(BOLD, "Healthcare Platform — Dev Metrics"))
    print(c(DIM, data["generated_at"]))
    print()

    git = data["git"]
    dirty = c(YELLOW, "dirty") if git["dirty"] else c(GREEN, "clean")
    print(c(BOLD, "Git"))
    print(f"  {git['branch']}  {git['commit']}  {dirty}")
    if not data["env_file"]:
        print(f"  {c(RED, 'missing .env.local')}  (copy from .env.local.example)")
    print()

    print(c(BOLD, "Services"))
    for s in data["services"]:
        extra = ""
        detail = s.get("detail")
        if isinstance(detail, list) and detail:
            extra = "  " + c(CYAN, ", ".join(str(x) for x in detail if x))
        http = ""
        if s["http_ok"] is True:
            http = c(GREEN, " http-ok")
        elif s["http_ok"] is False:
            http = c(YELLOW, " http-fail")
        print(
            f"  {_status_word(s['tcp'])}  {s['name']:<22} "
            f"{s['host']}:{s['port']}{http}{extra}"
        )
        if isinstance(detail, dict):
            for key, val in flatten(detail).items():
                print(f"      {key} = {val}")
    print()

    print(c(BOLD, "GPU"))
    gpu = data["gpu"]
    if not gpu:
        print(f"  {c(YELLOW, 'nvidia-smi unavailable')}  (expected on L4 / prod)")
    else:
        used = gpu.get("vram_used_mb")
        total = gpu.get("vram_total_mb")
        if used is not None and total:
            pct = 100.0 * used / total
            print(
                f"  {gpu.get('name')}  VRAM {used/1024:.1f}/{total/1024:.1f} GB "
                f"({pct:.0f}%)  util {gpu.get('util_pct')}%  "
                f"{gpu.get('temp_c')}°C  {gpu.get('power_w')}W"
            )
        else:
            print(f"  {gpu}")
    print()

    print(c(BOLD, "Storage artifacts"))
    a = data["artifacts"]
    rows = [
        ("PDFs", a["pdfs"], a["pdfs_bytes"]),
        ("OCR / extract", a["ocr"], None),
        ("Markdown / convert", a["markdown"], None),
        ("Clean", a["cleaned"], None),
        ("Chunks (all files)", a["chunks"], None),
        ("Chunk JSON", a["chunk_json"], None),
    ]
    for label, n, size in rows:
        size_s = f"  {fmt_bytes(size)}" if size is not None else ""
        print(f"  {label:<22} {n:>6}{size_s}")
    print(f"  {'artifacts dir':<22} {fmt_bytes(a['artifacts_bytes']):>6}")
    print()

    print(c(BOLD, "Qdrant"))
    q = data["qdrant"]
    if not q.get("reachable"):
        print(f"  {c(YELLOW, 'unreachable')}  {c(DIM, 'make up  then retry')}")
    else:
        cols = q.get("collections") or []
        if not cols:
            print(f"  {c(YELLOW, 'no collections')}")
        for col in cols:
            if col.get("error"):
                print(f"  {col['name']}: error reading collection")
                continue
            print(
                f"  {col['name']}:  points={col.get('points_count')}  "
                f"indexed={col.get('indexed_vectors_count')}  "
                f"segments={col.get('segments_count')}  "
                f"status={col.get('status')}  "
                f"dim={col.get('vector_size')}  "
                f"metric={col.get('distance')}"
            )
    print()

    print(c(BOLD, "Neo4j"))
    n = data["neo4j"]
    if not n.get("reachable") or n.get("error"):
        print(f"  {c(YELLOW, n.get('error') or 'unreachable')}")
    else:
        print(f"  nodes={n.get('nodes')}  relationships={n.get('relationships')}")
        if n.get("labels"):
            print("  labels:")
            for item in n["labels"]:
                print(f"    {item['name']:<24} {item['count']}")
        if n.get("relationship_types"):
            print("  relationship types:")
            for item in n["relationship_types"]:
                print(f"    {item['name']:<24} {item['count']}")
    print()

    print(c(BOLD, "Inference"))
    inf = data["inference"]
    for key, label in (
        ("sglang", "SGLang :30000"),
        ("ollama", "Ollama :11434"),
        ("lm_studio", "LM Studio :1234"),
    ):
        block = inf.get(key) or {}
        models = block.get("models") or []
        model_s = ", ".join(str(m) for m in models if m) or "—"
        print(f"  {_status_word(bool(block.get('reachable')))}  {label:<20} {model_s}")
        if block.get("cache"):
            for ck, cv in flatten(block["cache"]).items():
                print(f"    cache.{ck} = {cv}")
    print()

    print(c(BOLD, "Benchmark (latest run)"))
    b = data["benchmark"]
    if not b.get("present"):
        print(
            f"  {c(YELLOW, 'no benchmarking/results/* yet')}  "
            f"{c(DIM, 'make benchmark-all  or  make deterministic-run')}"
        )
        print()
        return
    print(f"  run_dir  {b.get('run_dir')}")
    skip = {"present", "run_dir"}
    for stage, payload in b.items():
        if stage in skip:
            continue
        print(c(CYAN, f"  [{stage}]"))
        for key, val in flatten(payload).items():
            if isinstance(val, str) and len(val) > 120:
                val = val[:117] + "…"
            print(f"    {key} = {val}")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Print every live platform metric")
    parser.add_argument("--json", action="store_true", help="Machine-readable dump")
    parser.add_argument(
        "--run-dir",
        type=Path,
        default=None,
        help="Benchmark results directory (default: newest under benchmarking/results)",
    )
    args = parser.parse_args()
    run_dir = args.run_dir
    if run_dir and not run_dir.is_absolute():
        run_dir = (Path.cwd() / run_dir).resolve()
    data = collect(latest_run_dir(run_dir))
    if args.json:
        json.dump(data, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
    else:
        print_human(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
