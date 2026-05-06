"""
Tests for data-acquisition config_loader:
  - resolve_source_name: various identifier forms
  - _expand_env_vars: recursion, missing vars, non-string pass-through
"""

import os
import pytest
from src.config_loader import resolve_source_name, _expand_env_vars


# ---------------------------------------------------------------------------
# Shared mock acquisition config
# ---------------------------------------------------------------------------

MOCK_ACQ_CONFIG = {
    "sources": {
        "medrxiv": {"name": "medrxiv", "url": "https://medrxiv.org"},
        "biorxiv": {"name": "biorxiv", "url": "https://biorxiv.org"},
        "pubmed": {"name": "PubMed", "url": "https://ncbi.nlm.nih.gov"},
        "clinical_trials": {"name": "Clinical Trials", "url": "https://ct.gov"},
    }
}


# ---------------------------------------------------------------------------
# resolve_source_name
# ---------------------------------------------------------------------------

class TestResolveSourceName:
    def test_exact_key_resolves(self) -> None:
        assert resolve_source_name("medrxiv", MOCK_ACQ_CONFIG) == "medrxiv"

    def test_biorxiv_exact_key(self) -> None:
        assert resolve_source_name("biorxiv", MOCK_ACQ_CONFIG) == "biorxiv"

    def test_yaml_path_stem_resolves(self) -> None:
        result = resolve_source_name("sources/medrxiv.yaml", MOCK_ACQ_CONFIG)
        assert result == "medrxiv"

    def test_yml_extension_resolves(self) -> None:
        result = resolve_source_name("biorxiv.yml", MOCK_ACQ_CONFIG)
        assert result == "biorxiv"

    def test_underscore_to_hyphen_normalisation(self) -> None:
        # 'clinical_trials' is the key; 'clinical-trials' should normalize
        result = resolve_source_name("clinical-trials", MOCK_ACQ_CONFIG)
        assert result == "clinical_trials"

    def test_display_name_match(self) -> None:
        # 'pubmed' key has display name 'PubMed'
        result = resolve_source_name("pubmed", MOCK_ACQ_CONFIG)
        assert result == "pubmed"

    def test_display_name_clinical_trials(self) -> None:
        result = resolve_source_name("Clinical Trials", MOCK_ACQ_CONFIG)
        assert result == "clinical_trials"

    def test_unknown_source_raises_key_error(self) -> None:
        with pytest.raises(KeyError, match="Unknown acquisition source"):
            resolve_source_name("does_not_exist", MOCK_ACQ_CONFIG)

    def test_empty_string_raises_key_error(self) -> None:
        with pytest.raises(KeyError):
            resolve_source_name("", MOCK_ACQ_CONFIG)


# ---------------------------------------------------------------------------
# _expand_env_vars
# ---------------------------------------------------------------------------

class TestExpandEnvVars:
    def test_plain_string_unchanged(self) -> None:
        assert _expand_env_vars("hello world") == "hello world"

    def test_env_var_substituted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_SECRET_KEY", "hunter2")
        assert _expand_env_vars("${TEST_SECRET_KEY}") == "hunter2"

    def test_missing_env_var_becomes_empty_string(self) -> None:
        result = _expand_env_vars("${DEFINITELY_NOT_SET_XYZ_ABC_12345}")
        assert result == ""

    def test_env_var_embedded_in_longer_string(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DB_HOST", "localhost")
        result = _expand_env_vars("postgresql://${DB_HOST}/mydb")
        assert result == "postgresql://localhost/mydb"

    def test_multiple_vars_in_same_string(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("USER_A", "alice")
        monkeypatch.setenv("USER_B", "bob")
        result = _expand_env_vars("${USER_A}:${USER_B}")
        assert result == "alice:bob"

    def test_nested_dict_expanded_recursively(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BUCKET_NAME", "my-bucket")
        data = {
            "storage": {"bucket": "${BUCKET_NAME}"},
            "region": "us-east-1",
        }
        result = _expand_env_vars(data)
        assert result["storage"]["bucket"] == "my-bucket"
        assert result["region"] == "us-east-1"

    def test_list_items_expanded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("API_KEY", "abc123")
        result = _expand_env_vars(["${API_KEY}", "static", "${API_KEY}"])
        assert result == ["abc123", "static", "abc123"]

    def test_integer_value_passes_through_unchanged(self) -> None:
        assert _expand_env_vars(42) == 42

    def test_boolean_value_passes_through_unchanged(self) -> None:
        assert _expand_env_vars(True) is True

    def test_none_value_passes_through_unchanged(self) -> None:
        assert _expand_env_vars(None) is None

    def test_float_value_passes_through_unchanged(self) -> None:
        assert _expand_env_vars(3.14) == 3.14

    def test_deeply_nested_structure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("INNER_VAR", "FOUND")
        data = {"level1": {"level2": {"level3": "${INNER_VAR}"}}}
        result = _expand_env_vars(data)
        assert result["level1"]["level2"]["level3"] == "FOUND"
