from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field


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
    """Recursively resolve ${VAR} patterns in config values."""
    if isinstance(obj, str):
        return re.sub(r"\$\{([^}]+)\}", lambda m: os.environ.get(m.group(1), ""), obj)
    if isinstance(obj, dict):
        return {k: _expand_env_vars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_env_vars(item) for item in obj]
    return obj


def _normalize_agent_name(identifier: str | Path | None, app_config: dict[str, Any]) -> str:
    """Accept agent names or legacy YAML paths and normalize to an agent key."""
    configured_default = (
        app_config.get("agentic_reasoning", {})
        .get("defaults", {})
        .get("default_agent", "local_assistant")
    )
    if identifier is None:
        return configured_default

    raw = str(identifier).strip()
    if not raw:
        return configured_default

    candidate = Path(raw).stem if raw.endswith((".yaml", ".yml")) or "/" in raw else raw
    candidate = candidate.replace("-", "_")
    if candidate in app_config.get("agentic_reasoning", {}).get("agents", {}):
        return candidate

    agents = app_config.get("agentic_reasoning", {}).get("agents", {})
    for name, cfg in agents.items():
        cfg_name = str(cfg.get("name", "")).strip()
        if cfg_name == raw or cfg_name == candidate:
            return name

    raise FileNotFoundError(f"Agent config not found: {identifier}")


class ModelParams(BaseModel):
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    top_p: float = 0.9
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    response_format: Optional[dict[str, Any]] = None


class ToolConfig(BaseModel):
    name: str


class AgentConfig(BaseModel):
    name: str
    model: str
    system_prompt: Optional[str] = None
    model_params: ModelParams = Field(default_factory=ModelParams)
    tools: list[ToolConfig] = Field(default_factory=list)


def load_app_config(path: str | Path | None = None) -> dict[str, Any]:
    _load_dotenv()
    config_path = Path(path) if path else APP_CONFIG_PATH
    with open(config_path, "r") as f:
        data = yaml.safe_load(f) or {}
    return _expand_env_vars(data)


def load_agent_config(identifier: str | Path | None = None) -> AgentConfig:
    app_config = load_app_config()
    agent_name = _normalize_agent_name(identifier, app_config)
    data = app_config["agentic_reasoning"]["agents"][agent_name]
    return AgentConfig(**data)
