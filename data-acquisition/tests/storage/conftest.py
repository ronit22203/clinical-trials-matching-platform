"""
Pytest fixtures for storage integration tests.

Provides fixtures for AWS S3, Azure Blob, and local fallback storage testing.
"""

import importlib.util
import os
import uuid
from pathlib import Path

import pytest
from src.config_loader import load_acquisition_config

_CLOUD_TEST_FILES = {
    "test_aws_s3.py",
    "test_azure_blob.py",
    "test_storage_integration.py",
    "test_utils.py",
}


def pytest_ignore_collect(collection_path, config):
    """Skip cloud-provider test files when optional cloud deps are not installed."""
    if collection_path.name in _CLOUD_TEST_FILES:
        if importlib.util.find_spec("boto3") is None:
            return True
    return None



@pytest.fixture(scope="session")
def acquisition_config() -> dict:
    """Load data-acquisition config from config/app.yaml."""
    return load_acquisition_config()


@pytest.fixture
def aws_s3_config(acquisition_config: dict) -> dict:
    """Load AWS S3 storage configuration."""
    return acquisition_config["storage"]["aws_s3"]


@pytest.fixture
def azure_blob_config(acquisition_config: dict) -> dict:
    """Load Azure Blob storage configuration."""
    return acquisition_config["storage"]["azure_blob"]


@pytest.fixture
def local_fallback_config(acquisition_config: dict) -> dict:
    """Load local fallback storage configuration."""
    return acquisition_config["storage"]["local_fallback"]


@pytest.fixture
def providers_config(acquisition_config: dict) -> dict:
    """Load providers configuration."""
    return acquisition_config["storage"]["providers"]


@pytest.fixture
def test_prefix() -> str:
    """Generate a unique test prefix for each test run."""
    return f"test-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def temp_dir(tmp_path: Path) -> Path:
    """Create a temporary directory for local storage tests."""
    test_dir = tmp_path / "graphrag_fallback_test"
    test_dir.mkdir(parents=True, exist_ok=True)
    return test_dir


@pytest.fixture
def sample_pdf_content() -> bytes:
    """Sample PDF content for testing (minimal valid PDF header)."""
    return b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"


@pytest.fixture
def sample_metadata() -> dict:
    """Sample metadata for testing."""
    return {
        "nct_id": "NCT01234567",
        "brief_title": "Test Clinical Trial",
        "overall_status": "Recruiting",
        "lead_sponsor_name": "Test Hospital",
        "study_type": "Interventional",
        "phase": "Phase 3",
        "enrollment_count": 100,
        "last_update_post_date": "2026-03-03",
        "fetched_at": "2026-03-03T00:00:00Z",
        "source_version": "1.0",
        "pdf_type": "protocol",
    }


@pytest.fixture
def aws_credentials() -> dict:
    """AWS credentials from environment."""
    return {
        "profile": os.environ.get("AWS_PROFILE", "default"),
        "region": os.environ.get("AWS_DEFAULT_REGION", "ap-south-1"),
        "access_key_id": os.environ.get("AWS_ACCESS_KEY_ID"),
        "secret_access_key": os.environ.get("AWS_SECRET_ACCESS_KEY"),
    }


@pytest.fixture
def azure_credentials() -> dict:
    """Azure credentials from environment."""
    return {
        "connection_string": os.environ.get("AZURE_STORAGE_CONNECTION_STRING"),
        "account_name": os.environ.get("AZURE_STORAGE_ACCOUNT"),
        "account_key": os.environ.get("AZURE_STORAGE_KEY"),
    }


@pytest.fixture
def is_ci() -> bool:
    """Check if running in CI environment."""
    return os.environ.get("CI", "").lower() in ("true", "1", "yes")


@pytest.fixture
def skip_if_no_aws_credentials(aws_credentials: dict, is_ci: bool):
    """Skip test if AWS credentials are not available."""
    if is_ci:
        pytest.skip("Skipping AWS tests in CI without credentials")
    if not any([aws_credentials.get("access_key_id"), aws_credentials.get("profile")]):
        pytest.skip("AWS credentials not available")


@pytest.fixture
def skip_if_no_azure_credentials(azure_credentials: dict, is_ci: bool):
    """Skip test if Azure credentials are not available."""
    if is_ci:
        pytest.skip("Skipping Azure tests in CI without credentials")
    if not azure_credentials.get("connection_string"):
        pytest.skip("Azure connection string not available")
