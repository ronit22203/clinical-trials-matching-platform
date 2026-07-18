"""
Integration tests for Azure Blob Storage.

Tests the fallback storage configuration using the actual Azure storage account.
"""

import os

import pytest

from azure.storage.blob import BlobServiceClient


pytestmark = pytest.mark.azure


class TestAzureBlobConnection:
    """Test Azure Blob storage connectivity."""

    @pytest.mark.integration
    def test_connection_string_format(self, azure_blob_config):
        """Verify connection string is properly configured."""
        conn_string = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
        assert conn_string, "AZURE_STORAGE_CONNECTION_STRING not set"
        assert "DefaultEndpointsProtocol=https" in conn_string
        assert "AccountName=" in conn_string
        assert "AccountKey=" in conn_string

    def test_storage_account_config(self, azure_blob_config):
        """Verify storage account configuration."""
        assert azure_blob_config["provider"] == "azure"
        assert azure_blob_config["account"] is not None
        assert azure_blob_config["resource_group"] is not None
        assert azure_blob_config["location"] == "centralindia"
        assert azure_blob_config["default"] is False  # fallback storage

    def test_container_config(self, azure_blob_config):
        """Verify container configuration."""
        container = azure_blob_config["containers"]["clinical-trials-fallback"]
        assert container["name"] == "clinical-trials-fallback"
        assert container["access_level"] == "private"
        assert container["versioning"] is True

    def test_blob_service_client_creation(self, azure_blob_config):
        """Test creating a blob service client."""
        conn_string = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
        if not conn_string:
            pytest.skip("Azure connection string not available")

        client = BlobServiceClient.from_connection_string(conn_string)
        assert client is not None
        assert client.account_name == os.environ.get("AZURE_STORAGE_ACCOUNT")


class TestAzureContainerOperations:
    """Test Azure container operations."""

    @pytest.fixture
    def blob_service_client(self, azure_blob_config):
        """Create blob service client."""
        conn_string = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
        if not conn_string:
            pytest.skip("Azure connection string not available")
        return BlobServiceClient.from_connection_string(conn_string)

    @pytest.fixture
    def container_client(self, blob_service_client, test_prefix):
        """Get container client for clinical-trials-fallback."""
        container_client = blob_service_client.get_container_client("clinical-trials-fallback")
        return container_client

    def test_container_exists(self, container_client):
        """Verify the clinical-trials-fallback container exists."""
        assert container_client.exists()

    def test_container_is_private(self, container_client):
        """Verify container has private access level."""
        props = container_client.get_container_properties()
        assert props["public_access"] is None

    def test_upload_and_download_blob(self, container_client, sample_pdf_content, test_prefix):
        """Test uploading and downloading a blob."""
        blob_name = f"{test_prefix}/test_upload.pdf"
        blob_client = container_client.get_blob_client(blob_name)

        try:
            # Upload
            blob_client.upload_blob(sample_pdf_content, overwrite=True)

            # Download
            download_stream = blob_client.download_blob()
            downloaded_content = download_stream.readall()

            assert downloaded_content == sample_pdf_content
        finally:
            # Cleanup
            blob_client.delete_blob()

    def test_upload_metadata_json(self, container_client, sample_metadata, test_prefix):
        """Test uploading metadata as JSON."""
        import json

        blob_name = f"{test_prefix}/metadata/test_metadata.json"
        blob_client = container_client.get_blob_client(blob_name)
        metadata_content = json.dumps(sample_metadata).encode("utf-8")

        try:
            blob_client.upload_blob(metadata_content, overwrite=True, content_settings={"content_type": "application/json"})

            # Verify
            download_stream = blob_client.download_blob()
            downloaded = json.loads(download_stream.readall().decode("utf-8"))

            assert downloaded["nct_id"] == sample_metadata["nct_id"]
            assert downloaded["brief_title"] == sample_metadata["brief_title"]
        finally:
            blob_client.delete_blob()

    def test_list_blobs_with_prefix(self, container_client, test_prefix):
        """Test listing blobs with a prefix."""
        # Upload test blobs
        blob_names = [
            f"{test_prefix}/raw/clinical_trials/test1.pdf",
            f"{test_prefix}/raw/clinical_trials/test2.pdf",
            f"{test_prefix}/metadata/test1.json",
        ]

        try:
            for name in blob_names:
                blob_client = container_client.get_blob_client(name)
                blob_client.upload_blob(b"test content", overwrite=True)

            # List with prefix
            blobs = list(container_client.list_blobs(name_starts_with=f"{test_prefix}/raw/"))
            blob_names_listed = [blob.name for blob in blobs]

            assert len(blob_names_listed) == 2
            assert f"{test_prefix}/raw/clinical_trials/test1.pdf" in blob_names_listed
        finally:
            # Cleanup all test blobs
            for name in blob_names:
                blob_client = container_client.get_blob_client(name)
                blob_client.delete_blob()


class TestAzurePathTemplates:
    """Test Azure path template rendering."""

    def test_raw_path_template(self, azure_blob_config, sample_metadata):
        """Test raw PDF path template."""
        paths = azure_blob_config["containers"]["clinical-trials-fallback"]["paths"]
        template = paths["raw"]

        rendered = template.format(
            source="clinical_trials",
            year="2026",
            month="03",
            day="03",
            nct_id=sample_metadata["nct_id"],
            pdf_type="protocol",
        )

        assert rendered == "raw/clinical_trials/2026/03/03/NCT01234567/protocol.pdf"

    def test_metadata_path_template(self, azure_blob_config, sample_metadata):
        """Test metadata path template."""
        paths = azure_blob_config["containers"]["clinical-trials-fallback"]["paths"]
        template = paths["metadata"]

        rendered = template.format(
            source="clinical_trials",
            year="2026",
            month="03",
            day="03",
            nct_id=sample_metadata["nct_id"],
        )

        assert rendered == "metadata/clinical_trials/2026/03/03/NCT01234567.json"

    def test_manifests_path_template(self, azure_blob_config):
        """Test manifests path template."""
        paths = azure_blob_config["containers"]["clinical-trials-fallback"]["paths"]
        template = paths["manifests"]

        rendered = template.format(
            source="clinical_trials",
            run_id="run-12345",
        )

        assert rendered == "manifests/clinical_trials/run-12345.json"


class TestAzureRetryConfiguration:
    """Test Azure retry configuration."""

    def test_retry_settings(self, azure_blob_config):
        """Verify retry configuration."""
        retry = azure_blob_config["retry"]
        assert retry["max_attempts"] == 3
        assert retry["backoff_factor"] == 2.0
        assert retry["timeout_seconds"] == 60


class TestAzureCostTracking:
    """Test Azure cost tracking configuration."""

    def test_cost_rates(self, azure_blob_config):
        """Verify cost rate configuration."""
        cost = azure_blob_config["cost"]
        assert cost["hot_storage_per_gb"] == 0.018
        assert cost["cool_storage_per_gb"] == 0.01
        assert cost["write_operations"] == 0.05
        assert cost["read_operations"] == 0.004

    def test_cost_tracking_enabled(self, azure_blob_config):
        """Verify cost tracking is enabled."""
        tracking = azure_blob_config["cost"]["tracking"]
        assert tracking["enabled"] is True
        assert tracking["budget_daily"] == 5
        assert tracking["alert_when_percent"] == 80
        assert tracking["tags"]["project"] == "multi-cloud-graphrag"
        assert tracking["tags"]["tier"] == "fallback"


class TestAzureFallbackTriggers:
    """Test Azure fallback trigger configuration."""

    def test_fallback_triggers(self, azure_blob_config):
        """Verify fallback triggers."""
        triggers = azure_blob_config["fallback_triggers"]
        assert "aws_s3_unavailable" in triggers
        assert "aws_s3_throttling" in triggers
        assert "cost_threshold_exceeded" in triggers
        assert "manual_override" in triggers
