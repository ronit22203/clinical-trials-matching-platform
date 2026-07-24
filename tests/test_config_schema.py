"""
Structural validation of config/app.yaml.

These tests guard against misconfiguration that would silently break runtime
behaviour across all four modules.  No module imports are needed — just yaml.
"""

import pytest
import yaml
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
_cfg = yaml.safe_load((_REPO_ROOT / "config" / "app.yaml").read_text()) or {}


# ---------------------------------------------------------------------------
# Top-level schema
# ---------------------------------------------------------------------------

class TestTopLevelSchema:
    REQUIRED_KEYS = {"services", "data_ingestion", "data_acquisition", "agentic_reasoning"}

    def test_required_top_level_keys_present(self):
        missing = self.REQUIRED_KEYS - set(_cfg.keys())
        assert not missing, f"config/app.yaml missing top-level keys: {missing}"

    def test_services_has_neo4j_qdrant(self):
        svcs = _cfg["services"]
        for svc in ("neo4j", "qdrant"):
            assert svc in svcs, f"services section missing: {svc!r}"

    def test_services_neo4j_has_uri(self):
        assert "uri" in _cfg["services"]["neo4j"]

    def test_services_qdrant_has_url(self):
        assert "url" in _cfg["services"]["qdrant"]


# ---------------------------------------------------------------------------
# data_ingestion section
# ---------------------------------------------------------------------------

class TestIngestionConfig:
    @pytest.fixture(autouse=True)
    def ingestion(self):
        self._ing = _cfg["data_ingestion"]

    def test_output_dirs_defined(self):
        out = self._ing["output"]
        for key in ("ocr_dir", "markdown_dir", "cleaned_dir", "chunks_dir"):
            assert key in out, f"data_ingestion.output missing: {key!r}"

    def test_chunking_params_sane(self):
        chk = self._ing["chunking"]
        assert chk["max_tokens"] > 0, "max_tokens must be positive"
        assert chk["chunk_overlap"] >= 0, "chunk_overlap cannot be negative"
        assert chk["min_chunk_tokens"] >= 0, "min_chunk_tokens cannot be negative"
        assert chk["chunk_overlap"] < chk["max_tokens"], "overlap must be < max_tokens"

    def test_cleaning_section_present(self):
        assert "cleaning" in self._ing

    def test_vectorization_has_model_and_collection(self):
        vec = self._ing["vectorization"]
        assert "model_name" in vec
        assert "collection_name" in vec
        assert "patient_context_collection" in vec
        assert vec["patient_context_collection"] != vec["collection_name"]
        assert vec["embedding_dim"] > 0

    def test_knowledge_graph_has_explicit_fallback(self):
        kg = self._ing["knowledge_graph"]
        assert kg["chat_url"]
        assert kg["fallback_chat_url"]
        assert kg["fallback_model"]
        assert kg["health_timeout_seconds"] > 0

    def test_ocr_confidence_threshold_in_range(self):
        threshold = self._ing["ocr"].get("confidence_threshold", 0.8)
        assert 0.0 <= threshold <= 1.0


# ---------------------------------------------------------------------------
# data_acquisition section
# ---------------------------------------------------------------------------

class TestAcquisitionConfig:
    @pytest.fixture(autouse=True)
    def acquisition(self):
        self._acq = _cfg["data_acquisition"]

    def test_sources_section_exists_and_non_empty(self):
        assert "sources" in self._acq
        assert len(self._acq["sources"]) > 0, "At least one acquisition source required"

    def test_each_source_has_name_field(self):
        for source_key, source_cfg in self._acq["sources"].items():
            assert "name" in source_cfg, f"source {source_key!r} missing 'name'"

    def test_storage_providers_chain_priority_ordered(self):
        chain = self._acq["storage"]["providers"]["chain"]
        assert len(chain) > 0, "Provider chain must have at least one entry"
        priorities = [e["priority"] for e in chain]
        assert priorities == sorted(priorities), (
            f"Provider chain is not sorted by priority: {priorities}"
        )

    def test_each_provider_entry_has_provider_key(self):
        chain = self._acq["storage"]["providers"]["chain"]
        for entry in chain:
            assert "provider" in entry, f"Chain entry missing 'provider': {entry}"

    def test_defaults_section_exists(self):
        assert "defaults" in self._acq


# ---------------------------------------------------------------------------
# agentic_reasoning section
# ---------------------------------------------------------------------------

class TestAgenticReasoningConfig:
    @pytest.fixture(autouse=True)
    def reasoning(self):
        self._ar = _cfg["agentic_reasoning"]

    @property
    def _agent_configs(self):
        if "agent" in self._ar:
            return {"default": self._ar["agent"]}
        return self._ar.get("agents", {})

    def test_agent_configuration_non_empty(self):
        assert self._agent_configs, "At least one agent definition is required"

    def test_default_agent_references_existing_agent(self):
        default = self._ar.get("defaults", {}).get("default_agent")
        if default:
            assert default in self._agent_configs, (
                f"default_agent={default!r} is not defined in agents section"
            )

    def test_each_agent_has_model_and_system_prompt(self):
        for agent_key, agent_cfg in self._agent_configs.items():
            assert "model" in agent_cfg, f"agent {agent_key!r} missing 'model'"
            assert "system_prompt" in agent_cfg, f"agent {agent_key!r} missing 'system_prompt'"

    def test_tools_section_has_module_and_class(self):
        tools = self._ar.get("tools", {})
        for tool_name, tool_cfg in tools.items():
            assert "module" in tool_cfg, f"tool {tool_name!r} missing 'module'"
            assert "class_name" in tool_cfg, f"tool {tool_name!r} missing 'class_name'"

    def test_model_params_temperature_in_range(self):
        """All configured model_params must have a temperature in [0.0, 2.0]."""
        for agent_key, agent_cfg in self._agent_configs.items():
            params = agent_cfg.get("model_params", {})
            if "temperature" in params:
                assert 0.0 <= params["temperature"] <= 2.0, (
                    f"agent {agent_key!r}: temperature out of range"
                )

    def test_reasoning_agent_has_explicit_fallback_and_retrieval_guardrails(self):
        agent = self._ar["agent"]
        graphrag = self._ar["graphrag"]["config"]
        assert agent["fallback_model"].startswith("lmstudio/")
        assert agent["health_check_timeout_seconds"] > 0
        assert graphrag["scope"] == "literature"
        assert -1.0 <= graphrag["min_relevance_score"] <= 1.0
