"""
Agent configuration — flat Pydantic v2 models loaded from config/app.yaml.

Replaces the old multi-agent config_loader.py. Single agent, single tool (GraphRAG).
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field, field_validator

_REPO_ROOT = Path(__file__).resolve().parents[2]
APP_CONFIG_PATH = _REPO_ROOT / "config" / "app.yaml"


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ModelParams(BaseModel):
    temperature: float = 0.1
    max_tokens: Optional[int] = 4096
    top_p: float = 0.9
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0


class GraphRAGConfig(BaseModel):
    qdrant_url: str = "http://localhost:6333"
    collection: str = "medical_papers"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    model_cache_dir: str = "data/models"
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_username: str = "neo4j"
    neo4j_password: str = "password"
    scope: str = "literature"
    min_relevance_score: float = Field(default=0.35, ge=-1.0, le=1.0)
    limit: int = 3
    neo4j_limit: int = 10
    reranker_model: Optional[str] = None
    retrieval_k: Optional[int] = None
    cache_ttl: int = 300
    cache_maxsize: int = 128


class AgentConfig(BaseModel):
    model: str = "lmstudio/qwen3-8b"
    fallback_model: Optional[str] = None
    health_check_timeout_seconds: float = Field(default=2.0, gt=0.0, le=30.0)
    system_prompt: str = (
        "You are a clinical research assistant. "
        "Answer ONLY using the evidence retrieved from the knowledge base. "
        "Do not use parametric memory when evidence is available."
    )
    model_params: ModelParams = Field(default_factory=ModelParams)
    graphrag: GraphRAGConfig = Field(default_factory=GraphRAGConfig)

    @field_validator("model")
    @classmethod
    def primary_model_has_provider_and_name(cls, value: str) -> str:
        return cls._validate_model_identifier(value, field_name="model")

    @field_validator("fallback_model")
    @classmethod
    def fallback_model_has_provider_and_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return cls._validate_model_identifier(value, field_name="fallback_model")

    @staticmethod
    def _validate_model_identifier(value: str, *, field_name: str) -> str:
        normalized = value.strip()
        provider, separator, model_name = normalized.partition("/")
        if not provider or not separator or not model_name.strip():
            raise ValueError(
                f"{field_name} must use the provider/model-name format; "
                "set the corresponding environment variable before startup."
            )
        return normalized


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def _load_dotenv() -> None:
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


def load_config(path: Path | None = None) -> AgentConfig:
    """Load AgentConfig from the app.yaml agentic_reasoning section."""
    _load_dotenv()
    config_path = path or APP_CONFIG_PATH
    with open(config_path) as f:
        raw = yaml.safe_load(f) or {}
    raw = _expand_env_vars(raw)

    ar = raw.get("agentic_reasoning", {})
    agent_section = ar.get("agent", {})
    graphrag_section = ar.get("graphrag", {})

    model_params_data = agent_section.get("model_params", {})
    graphrag_data = graphrag_section.get("config", graphrag_section)

    return AgentConfig(
        model=agent_section.get("model", ar.get("defaults", {}).get("model", "lmstudio/qwen3-8b")),
        fallback_model=agent_section.get("fallback_model"),
        health_check_timeout_seconds=agent_section.get("health_check_timeout_seconds", 2.0),
        system_prompt=agent_section.get("system_prompt", AgentConfig.model_fields["system_prompt"].default),
        model_params=ModelParams(**model_params_data) if model_params_data else ModelParams(),
        graphrag=GraphRAGConfig(**graphrag_data) if graphrag_data else GraphRAGConfig(),
    )
