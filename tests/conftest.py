"""
Global fixtures shared across all root-level test modules.

sys.path isolation for each module is handled in subdirectory conftest files.
"""

import pytest
import yaml
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
APP_CONFIG_PATH = REPO_ROOT / "config" / "app.yaml"


@pytest.fixture(scope="session")
def app_config() -> dict:
    with open(APP_CONFIG_PATH) as f:
        return yaml.safe_load(f) or {}


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT
