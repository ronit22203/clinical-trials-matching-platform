"""
Tests for ToolRegistry: fault-isolated loading, get/list, disabled tools.
"""

import pytest

from src.tools.registry import ToolRegistry
from src.tools.implementations.openfda import OpenFDATool
from src.tools.implementations.clinicaltrials import ClinicalTrialsTool

# ---------------------------------------------------------------------------
# Minimal valid tool config dicts (mirror config/app.yaml structure)
# ---------------------------------------------------------------------------

_FDA_ENTRY = {
    "name": "fda",
    "module": "src.tools.implementations.openfda",
    "class_name": "OpenFDATool",
    "config": {"base_url": "https://api.fda.gov", "endpoint": "/drug/event.json"},
    "enabled": True,
}

_CT_ENTRY = {
    "name": "clinical_trials",
    "module": "src.tools.implementations.clinicaltrials",
    "class_name": "ClinicalTrialsTool",
    "config": {"base_url": "https://clinicaltrials.gov", "endpoint": "/api/v2/studies"},
    "enabled": True,
}

_BROKEN_ENTRY = {
    "name": "broken_tool",
    "module": "nonexistent.module.xyz",
    "class_name": "FakeTool",
    "config": {},
    "enabled": True,
}

_DISABLED_ENTRY = {
    "name": "disabled_tool",
    "module": "src.tools.implementations.openfda",
    "class_name": "OpenFDATool",
    "config": {},
    "enabled": False,
}


# ---------------------------------------------------------------------------
# Empty registry
# ---------------------------------------------------------------------------

class TestEmptyRegistry:
    def test_no_tools_listed(self) -> None:
        assert ToolRegistry({}).list_tools() == []

    def test_get_missing_tool_returns_none(self) -> None:
        assert ToolRegistry({}).get_tool("anything") is None


# ---------------------------------------------------------------------------
# Valid tool loading
# ---------------------------------------------------------------------------

class TestValidToolLoading:
    def test_single_valid_tool_appears_in_list(self) -> None:
        reg = ToolRegistry({"fda": _FDA_ENTRY})
        assert "fda" in reg.list_tools()

    def test_loaded_tool_is_correct_class(self) -> None:
        reg = ToolRegistry({"fda": _FDA_ENTRY})
        tool = reg.get_tool("fda")
        assert isinstance(tool, OpenFDATool)

    def test_multiple_valid_tools_all_loaded(self) -> None:
        reg = ToolRegistry({"fda": _FDA_ENTRY, "clinical_trials": _CT_ENTRY})
        tools = reg.list_tools()
        assert "fda" in tools
        assert "clinical_trials" in tools

    def test_tool_config_passed_through_to_instance(self) -> None:
        reg = ToolRegistry({"fda": _FDA_ENTRY})
        tool = reg.get_tool("fda")
        assert tool.config.get("base_url") == "https://api.fda.gov"


# ---------------------------------------------------------------------------
# Fault isolation
# ---------------------------------------------------------------------------

class TestFaultIsolation:
    def test_broken_module_does_not_raise_on_init(self) -> None:
        """A tool that fails to import must NOT crash the registry."""
        reg = ToolRegistry({"bad": _BROKEN_ENTRY})  # must not raise

    def test_broken_tool_absent_from_list(self) -> None:
        reg = ToolRegistry({"bad": _BROKEN_ENTRY})
        assert "bad" not in reg.list_tools()

    def test_broken_tool_does_not_block_valid_tool(self) -> None:
        reg = ToolRegistry({"fda": _FDA_ENTRY, "bad": _BROKEN_ENTRY})
        assert "fda" in reg.list_tools()
        assert "bad" not in reg.list_tools()

    def test_multiple_broken_tools_all_isolated(self) -> None:
        good_entry = {**_FDA_ENTRY, "name": "good_fda"}
        cfg = {
            "bad1": {**_BROKEN_ENTRY, "name": "bad1"},
            "bad2": {**_BROKEN_ENTRY, "name": "bad2", "module": "another.missing"},
            "good_fda": good_entry,
        }
        reg = ToolRegistry(cfg)
        assert reg.list_tools() == ["good_fda"]


# ---------------------------------------------------------------------------
# Disabled tools
# ---------------------------------------------------------------------------

class TestDisabledTools:
    def test_disabled_tool_not_in_list(self) -> None:
        reg = ToolRegistry({"disabled_tool": _DISABLED_ENTRY})
        assert "disabled_tool" not in reg.list_tools()

    def test_disabled_tool_not_retrievable(self) -> None:
        reg = ToolRegistry({"disabled_tool": _DISABLED_ENTRY})
        assert reg.get_tool("disabled_tool") is None

    def test_mix_of_enabled_disabled(self) -> None:
        reg = ToolRegistry({"fda": _FDA_ENTRY, "off": _DISABLED_ENTRY})
        assert "fda" in reg.list_tools()
        assert "off" not in reg.list_tools()
