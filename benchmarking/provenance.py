"""
provenance.py — Deterministic run provenance snapshot.

Captures everything needed to reproduce a benchmark run:
  - git commit hash
  - sha256 of config files
  - sha256 of the golden PDF
  - chunk count from the canonical chunks file
  - Qdrant collection point count
  - model names from app.yaml
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def _git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"


def _git_dirty() -> bool:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return bool(result.stdout.strip())
    except Exception:
        return False


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
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def _qdrant_point_count(qdrant_url: str, collection: str) -> int | None:
    try:
        import urllib.request
        url = f"{qdrant_url}/collections/{collection}"
        with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310
            data = json.loads(resp.read())
        return data["result"]["points_count"]
    except Exception:
        return None


def capture(run_id: str, config_path: Path | None = None) -> dict[str, Any]:
    """Return a provenance manifest dict for the given run_id."""
    cfg_path = config_path or (_REPO_ROOT / "config" / "app.yaml")
    with open(cfg_path) as f:
        raw_yaml = f.read()

    app_cfg: dict[str, Any] = yaml.safe_load(raw_yaml) or {}
    env = _load_env()

    def _resolve_env(val: str) -> str:
        import re
        return re.sub(r"\$\{([^}]+)\}", lambda m: env.get(m.group(1), ""), val)

    services_cfg = app_cfg.get("services", {})
    qdrant_url = _resolve_env(services_cfg.get("qdrant", {}).get("url", "http://localhost:6333"))
    qdrant_collection = services_cfg.get("qdrant", {}).get("collection", "medical_papers")

    # Config hashes
    extra_cfg = _REPO_ROOT / "config"
    config_hashes: dict[str, str] = {}
    if cfg_path.exists():
        config_hashes["app.yaml"] = f"sha256:{_sha256(cfg_path)}"
    for extra in extra_cfg.glob("*.yaml"):
        if extra != cfg_path:
            config_hashes[extra.name] = f"sha256:{_sha256(extra)}"

    # Input data
    chunks_file = _REPO_ROOT / "data" / "artifacts" / "chunk" / "2026.03.17.26348414_chunks.json"
    pdf_path = next(
        iter((_REPO_ROOT / "data" / "pdfs").rglob("*.pdf")),
        None,
    )

    input_data: dict[str, Any] = {
        "chunks_file": str(chunks_file.relative_to(_REPO_ROOT)) if chunks_file.exists() else None,
        "chunks_sha256": f"sha256:{_sha256(chunks_file)}" if chunks_file.exists() else None,
        "pdf_file": str(pdf_path.relative_to(_REPO_ROOT)) if pdf_path else None,
        "pdf_sha256": f"sha256:{_sha256(pdf_path)}" if pdf_path else None,
        "qdrant_collection": qdrant_collection,
        "qdrant_points": _qdrant_point_count(qdrant_url, qdrant_collection),
    }
    if chunks_file.exists():
        with open(chunks_file) as f:
            chunks_data = json.load(f)
        input_data["chunks_count"] = chunks_data.get("total_chunks", len(chunks_data.get("chunks", [])))

    # Model names from agentic-reasoning config
    ar_cfg = app_cfg.get("agentic_reasoning", {})
    tools_cfg = ar_cfg.get("tools", {})
    graphrag_cfg = tools_cfg.get("graphrag", {}).get("config", {})
    embedding_model = graphrag_cfg.get("embedding_model", "unknown")

    agents = ar_cfg.get("agents", {})
    agent_model = "unknown"
    if agents:
        first_agent = next(iter(agents.values()))
        agent_model = first_agent.get("model", "unknown")

    ingestion_cfg = app_cfg.get("data_ingestion", {})
    kg_cfg = ingestion_cfg.get("knowledge_graph", {})
    kg_model = kg_cfg.get("model", "unknown")

    return {
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_commit(),
        "git_dirty": _git_dirty(),
        "config_files": config_hashes,
        "models": {
            "embedding": embedding_model,
            "kg_extraction": kg_model,
            "agent_reasoning": agent_model,
        },
        "input_data": input_data,
    }


def write_manifest(run_dir: Path, run_id: str, config_path: Path | None = None) -> dict[str, Any]:
    """Write manifest.json to run_dir and return the manifest dict."""
    manifest = capture(run_id, config_path)
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = run_dir / "manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    return manifest


if __name__ == "__main__":
    import sys
    run_id = sys.argv[1] if len(sys.argv) > 1 else f"bench_{int(time.time())}"
    m = capture(run_id)
    print(json.dumps(m, indent=2))
