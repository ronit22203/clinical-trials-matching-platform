from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

APP_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "app.yaml"
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv() -> None:
    """Load .env.local from repo root into os.environ (without overwriting existing vars)."""
    env_file = _REPO_ROOT / ".env.local"
    if not env_file.exists():
        return
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def _expand_env_vars(obj: Any) -> Any:
    if isinstance(obj, str):
        return re.sub(r"\$\{([^}]+)\}", lambda m: os.environ.get(m.group(1), ""), obj)
    if isinstance(obj, dict):
        return {k: _expand_env_vars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_env_vars(item) for item in obj]
    return obj


def load_app_config(path: str | Path | None = None) -> dict[str, Any]:
    _load_dotenv()
    config_path = Path(path) if path else APP_CONFIG_PATH
    with open(config_path, "r") as f:
        data = yaml.safe_load(f) or {}
    return _expand_env_vars(data)


def load_acquisition_config(path: str | Path | None = None) -> dict[str, Any]:
    data = load_app_config(path)
    return data["data_acquisition"]


def resolve_source_name(identifier: str, acquisition_config: dict[str, Any] | None = None) -> str:
    cfg = acquisition_config or load_acquisition_config()
    sources = cfg.get("sources", {})
    raw = str(identifier).strip()
    candidate = Path(raw).stem if raw.endswith((".yaml", ".yml")) or "/" in raw else raw
    candidate = candidate.replace("-", "_")
    if candidate in sources:
        return candidate

    for name, source_cfg in sources.items():
        source_name = str(source_cfg.get("name", "")).strip()
        if source_name == candidate or source_name.replace("_", "") == candidate.replace("_", ""):
            return name
        if name.replace("_", "") == candidate.replace("_", ""):
            return name

    raise KeyError(f"Unknown acquisition source: {identifier}")


def load_source_config(identifier: str, path: str | Path | None = None) -> dict[str, Any]:
    acquisition_config = load_acquisition_config(path)
    source_name = resolve_source_name(identifier, acquisition_config)
    return acquisition_config["sources"][source_name]
