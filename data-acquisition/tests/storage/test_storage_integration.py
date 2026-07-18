"""
Multi-cloud storage integration tests.

Tests the storage provider selection, failover logic, and cross-cloud operations.
"""

import os

import pytest

import boto3
from azure.storage.blob import BlobServiceClient


pytestmark = pytest.mark.integration


class TestStorageProviderSelection:
    """Test storage provider selection logic."""

    def test_primary_provider_is_aws(self, aws_s3_config, azure_blob_config):
        """Verify AWS S3 is configured as primary."""
        assert aws_s3_config["default"] is True
        assert azure_blob_config["default"] is False

    def test_provider_priority_order(self, aws_s3_config, azure_blob_config, local_fallback_config):
        """Verify provider priority order."""
        # AWS: primary (priority 1)
        # Azure: fallback (priority 2)
        # Local: catastrophic (priority 99)
        assert aws_s3_config["default"] is True
        assert azure_blob_config["default"] is False
        assert local_fallback_config["priority"] == 99


class TestStorageConfigConsistency:
    """Test consistency across storage configurations."""

    def test_path_templates_match(self, aws_s3_config, azure_blob_config):
        """Verify path templates are consistent between AWS and Azure."""
        aws_paths = aws_s3_config["buckets"]["clinical-trials-pdfs"]["paths"]
        azure_paths = azure_blob_config["containers"]["clinical-trials-fallback"]["paths"]

        # Both should have same path structure
        assert "raw" in aws_paths
        assert "raw" in azure_paths
        assert "metadata" in aws_paths
        assert "metadata" in azure_paths
        assert "manifests" in aws_paths
        assert "manifests" in azure_paths

    def test_container_bucket_naming(self, aws_s3_config, azure_blob_config):
        """Verify naming consistency."""
        aws_container = aws_s3_config["buckets"]["clinical-trials-pdfs"]["name"]
        azure_container = azure_blob_config["containers"]["clinical-trials-fallback"]["name"]

        # Both should reference clinical trials
        assert "clinical" in aws_container.lower()
        assert "clinical" in azure_container.lower()


class TestFailoverLogic:
    """Test failover logic configuration."""

    def test_azure_fallback_triggers(self, azure_blob_config):
        """Verify Azure fallback triggers."""
        triggers = azure_blob_config["fallback_triggers"]
        assert len(triggers) >= 4
        assert "aws_s3_unavailable" in triggers
        assert "aws_s3_throttling" in triggers

    def test_local_triggers(self, local_fallback_config):
        """Verify local fallback triggers."""
        triggers = local_fallback_config["triggers"]
        assert "both_clouds_unavailable" in triggers
        assert "budget_exhausted" in triggers


class TestCrossCloudUpload:
    """Test cross-cloud upload scenarios."""

    @pytest.fixture
    def storage_clients(self, aws_s3_config, azure_blob_config):
        """Initialize storage clients for both clouds."""
        clients = {"aws": None, "azure": None}

        # Try AWS
        try:
            session = boto3.Session(profile_name=aws_s3_config["profile"])
            clients["aws"] = {
                "client": session.client("s3", region_name=aws_s3_config["region"]),
                "bucket": aws_s3_config["buckets"]["clinical-trials-pdfs"]["name"],
            }
        except Exception:
            pass

        # Try Azure
        conn_string = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
        if conn_string:
            clients["azure"] = {
                "client": BlobServiceClient.from_connection_string(conn_string),
                "container": "clinical-trials-fallback",
            }

        return clients

    def test_azure_available_as_fallback(self, storage_clients):
        """Verify Azure is available as fallback."""
        assert storage_clients["azure"] is not None, "Azure client should be available"

    @pytest.mark.skip(reason="Requires AWS credentials")
    def test_aws_primary_upload(self, storage_clients, sample_pdf_content, test_prefix):
        """Test upload to AWS primary storage."""
        if not storage_clients["aws"]:
            pytest.skip("AWS not available")

        aws = storage_clients["aws"]
        key = f"{test_prefix}/test_primary.pdf"

        aws["client"].put_object(
            Bucket=aws["bucket"],
            Key=key,
            Body=sample_pdf_content,
        )

        # Verify
        response = aws["client"].get_object(Bucket=aws["bucket"], Key=key)
        assert response["Body"].read() == sample_pdf_content

        # Cleanup
        aws["client"].delete_object(Bucket=aws["bucket"], Key=key)

    def test_azure_fallback_upload(self, storage_clients, sample_pdf_content, test_prefix):
        """Test upload to Azure fallback storage."""
        if not storage_clients["azure"]:
            pytest.skip("Azure not available")

        azure = storage_clients["azure"]
        container_client = azure["client"].get_container_client(azure["container"])
        blob_name = f"{test_prefix}/test_fallback.pdf"

        blob_client = container_client.get_blob_client(blob_name)
        blob_client.upload_blob(sample_pdf_content, overwrite=True)

        # Verify
        download_stream = blob_client.download_blob()
        assert download_stream.readall() == sample_pdf_content

        # Cleanup
        blob_client.delete_blob()


class TestStorageMetrics:
    """Test storage metrics configuration."""

    def test_aws_monitoring_config(self, aws_s3_config):
        """Verify AWS monitoring configuration."""
        monitoring = aws_s3_config["monitoring"]
        assert monitoring["cloudwatch_metrics"] is True
        assert monitoring["namespace"] == "GraphRAG/ClinicalTrials"

    def test_azure_monitoring_config(self, azure_blob_config):
        """Verify Azure monitoring configuration."""
        monitoring = azure_blob_config["monitoring"]
        assert monitoring["azure_monitor"] is True
        assert "log_analytics_workspace" in monitoring

    def test_cost_tracking_consistency(self, aws_s3_config, azure_blob_config):
        """Verify cost tracking is enabled on both providers."""
        aws_tracking = aws_s3_config["cost"]["tracking"]
        azure_tracking = azure_blob_config["cost"]["tracking"]

        assert aws_tracking["enabled"] is True
        assert azure_tracking["enabled"] is True


class TestStorageEncryption:
    """Test storage encryption configuration."""

    def test_aws_encryption(self, aws_s3_config):
        """Verify AWS encryption settings."""
        bucket = aws_s3_config["buckets"]["clinical-trials-pdfs"]
        assert bucket["encryption"] == "AES256"

    def test_azure_encryption(self, azure_blob_config):
        """Verify Azure encryption settings."""
        container = azure_blob_config["containers"]["clinical-trials-fallback"]
        assert container["default_encryption"] is True


class TestStorageVersioning:
    """Test storage versioning configuration."""

    def test_aws_versioning(self, aws_s3_config):
        """Verify AWS versioning settings."""
        bucket = aws_s3_config["buckets"]["clinical-trials-pdfs"]
        assert bucket["versioning"] is True

    def test_azure_versioning(self, azure_blob_config):
        """Verify Azure versioning settings."""
        container = azure_blob_config["containers"]["clinical-trials-fallback"]
        assert container["versioning"] is True


class TestStorageRetryConsistency:
    """Test retry configuration consistency."""

    def test_retry_max_attempts(self, aws_s3_config, azure_blob_config):
        """Verify both providers have same max retry attempts."""
        assert aws_s3_config["retry"]["max_attempts"] == 3
        assert azure_blob_config["retry"]["max_attempts"] == 3

    def test_retry_backoff(self, aws_s3_config, azure_blob_config):
        """Verify retry backoff configuration."""
        # AWS uses 1.5 with jitter
        # Azure uses 2.0 (more conservative)
        assert aws_s3_config["retry"]["backoff_factor"] == 1.5
        assert aws_s3_config["retry"]["jitter"] is True
        assert azure_blob_config["retry"]["backoff_factor"] == 2.0


class TestStorageBudgets:
    """Test budget configuration."""

    def test_aws_budget_config(self, aws_s3_config):
        """Verify AWS has cost tracking but no explicit budget."""
        # AWS tracks costs but budget is managed at source level
        tracking = aws_s3_config["cost"]["tracking"]
        assert tracking["enabled"] is True
        assert tracking["tag_uploads"] is True

    def test_azure_budget_config(self, azure_blob_config):
        """Verify Azure has explicit budget for fallback."""
        tracking = azure_blob_config["cost"]["tracking"]
        assert tracking["budget_daily"] == 5  # $5 per day for fallback
        assert tracking["alert_when_percent"] == 80
