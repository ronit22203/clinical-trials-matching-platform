"""
provenance.py — Deterministic run provenance snapshot.

Captures everything needed to reproduce a benchmark run:
  - git commit hash
  - sha256 of config files
  - sha256 of the golden PDF
  - chunk count from the canonical chunks file
  - Qdrant collection point count
  - model names from app.yaml
  - hardware: MacBook when the run is local, NVIDIA when a GPU host is production
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_BENCH_PDF = (
    "data/pdfs/raw/medrxiv/2026/04/22/10.64898/2026.03.17.26348414/paper.pdf"
)


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


def _nvidia_gpu_name() -> str | None:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    name = next((line.strip() for line in result.stdout.splitlines() if line.strip()), "")
    return name or None


def _mac_hardware() -> tuple[str | None, str | None]:
    model: str | None = None
    chip: str | None = None
    try:
        result = subprocess.run(
            ["system_profiler", "SPHardwareDataType"],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None, None
    if result.returncode != 0:
        return None, None
    for line in result.stdout.splitlines():
        key, separator, value = line.strip().partition(":")
        if not separator:
            continue
        if key == "Model Name":
            model = value.strip() or None
        elif key == "Chip":
            chip = value.strip() or None
    return model, chip


def classify_hardware(
    *,
    system: str,
    nvidia_name: str | None,
    mac_model: str | None,
    mac_chip: str | None,
) -> dict[str, str]:
    """Label a local Mac as a MacBook and a GPU server as NVIDIA."""
    if system == "Darwin":
        model = mac_model or "MacBook"
        if mac_chip and mac_chip not in model:
            device = f"{model} ({mac_chip})"
        else:
            device = model
        return {"environment": "local", "device": device}

    if nvidia_name:
        name = nvidia_name.strip()
        if not name.upper().startswith("NVIDIA"):
            name = f"NVIDIA {name}"
        return {"environment": "production", "device": name}

    return {"environment": "local", "device": system or "unknown"}


def detect_hardware() -> dict[str, str]:
    system = platform.system()
    mac_model, mac_chip = _mac_hardware() if system == "Darwin" else (None, None)
    return classify_hardware(
        system=system,
        nvidia_name=None if system == "Darwin" else _nvidia_gpu_name(),
        mac_model=mac_model,
        mac_chip=mac_chip,
    )


def _benchmark_pdf() -> Path | None:
    """The sepsis paper used by ``make deterministic-run``, not a stray upload."""
    relative = os.environ.get("BENCH_PDF") or _DEFAULT_BENCH_PDF
    candidate = (_REPO_ROOT / relative).resolve()
    if candidate.is_file():
        return candidate
    return next(iter((_REPO_ROOT / "data" / "pdfs").rglob("*.pdf")), None)


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

    # Input data. Prefer the PDF this run was asked to ingest.
    chunks_file = _REPO_ROOT / "data" / "artifacts" / "chunk" / "2026.03.17.26348414_chunks.json"
    pdf_path = _benchmark_pdf()

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
    graphrag_cfg = (ar_cfg.get("graphrag") or {}).get("config") or {}
    if not graphrag_cfg:
        graphrag_cfg = (
            (ar_cfg.get("tools") or {}).get("graphrag") or {}
        ).get("config") or {}
    embedding_model = graphrag_cfg.get("embedding_model", "unknown")

    agent_cfg = ar_cfg.get("agent") or {}
    if not agent_cfg:
        legacy_agents = ar_cfg.get("agents") or {}
        if legacy_agents:
            agent_cfg = next(iter(legacy_agents.values()))
    agent_model = agent_cfg.get("model", "unknown")

    ingestion_cfg = app_cfg.get("data_ingestion", {})
    kg_cfg = ingestion_cfg.get("knowledge_graph", {})
    kg_model = kg_cfg.get("model", "unknown")

    return {
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_commit(),
        "git_dirty": _git_dirty(),
        "hardware": detect_hardware(),
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
