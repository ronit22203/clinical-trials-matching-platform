"""
Integration tests for AWS S3 storage.

Tests the primary storage configuration using S3 directory buckets.
"""

import os
import json
from pathlib import Path
from datetime import datetime

import pytest

import boto3
from botocore.exceptions import ClientError, NoCredentialsError


pytestmark = pytest.mark.aws


class TestS3Connection:
    """Test AWS S3 connectivity."""

    def test_s3_config(self, aws_s3_config):
        """Verify S3 configuration."""
        assert aws_s3_config["provider"] == "aws"
        assert aws_s3_config["profile"] == "clinical-trials-fetcher"
        assert aws_s3_config["region"] == "ap-south-1"
        assert aws_s3_config["default"] is True  # primary storage

    def test_bucket_name_format(self, aws_s3_config):
        """Verify directory bucket name follows S3 Express One Zone format."""
        bucket_name = aws_s3_config["buckets"]["clinical-trials-pdfs"]["name"]
        # S3 Express One Zone buckets end with --x-s3
        assert bucket_name.endswith("--x-s3")
        assert "ap-south-1" in bucket_name
        assert "aps1-az1" in bucket_name

    def test_bucket_config(self, aws_s3_config):
        """Verify bucket configuration."""
        bucket = aws_s3_config["buckets"]["clinical-trials-pdfs"]
        assert isinstance(bucket["name"], str) and len(bucket["name"]) > 0
        assert isinstance(bucket["region"], str) and len(bucket["region"]) > 0
        assert bucket["versioning"] is True
        assert bucket["encryption"] == "AES256"
        assert bucket["lifecycle_days"] == 365

    def test_s3_client_creation(self, aws_s3_config):
        """Test creating an S3 client."""
        profile = aws_s3_config["profile"]
        region = aws_s3_config["region"]

        try:
            session = boto3.Session(profile_name=profile)
            client = session.client("s3", region_name=region)
            assert client is not None
        except (NoCredentialsError, ProfileNotFound):
            pytest.skip("AWS credentials not available")


class TestS3BucketOperations:
    """Test S3 bucket operations."""

    @pytest.fixture
    def s3_client(self, aws_s3_config):
        """Create S3 client."""
        try:
            session = boto3.Session(profile_name=aws_s3_config["profile"])
            return session.client("s3", region_name=aws_s3_config["region"])
        except (NoCredentialsError, Exception):
            pytest.skip("AWS credentials not available")

    @pytest.fixture
    def bucket_name(self, aws_s3_config):
        """Get bucket name from config."""
        return aws_s3_config["buckets"]["clinical-trials-pdfs"]["name"]

    def test_bucket_exists(self, s3_client, bucket_name):
        """Verify the bucket exists."""
        try:
            s3_client.head_bucket(Bucket=bucket_name)
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                pytest.fail(f"Bucket {bucket_name} does not exist")
            raise

    def test_bucket_versioning_enabled(self, s3_client, bucket_name):
        """Verify bucket versioning is enabled."""
        response = s3_client.get_bucket_versioning(Bucket=bucket_name)
        assert response.get("Status") == "Enabled"

    def test_bucket_encryption_enabled(self, s3_client, bucket_name):
        """Verify bucket encryption is enabled."""
        response = s3_client.get_bucket_encryption(Bucket=bucket_name)
        rules = response["ServerSideEncryptionConfiguration"]["Rules"]
        assert len(rules) > 0
        assert any(
            rule["ApplyServerSideEncryptionByDefault"]["SSEAlgorithm"] == "AES256"
            for rule in rules
        )

    def test_public_access_blocked(self, s3_client, bucket_name):
        """Verify public access is blocked."""
        response = s3_client.get_public_access_block(Bucket=bucket_name)
        config = response["PublicAccessBlockConfiguration"]
        assert config["BlockPublicAcls"] is True
        assert config["IgnorePublicAcls"] is True
        assert config["BlockPublicPolicy"] is True
        assert config["RestrictPublicBuckets"] is True

    def test_upload_and_download_object(self, s3_client, bucket_name, sample_pdf_content, test_prefix):
        """Test uploading and downloading an object."""
        key = f"{test_prefix}/raw/clinical_trials/test_upload.pdf"

        try:
            # Upload
            s3_client.put_object(
                Bucket=bucket_name,
                Key=key,
                Body=sample_pdf_content,
                ContentType="application/pdf",
            )

            # Download
            response = s3_client.get_object(Bucket=bucket_name, Key=key)
            downloaded_content = response["Body"].read()

            assert downloaded_content == sample_pdf_content
        finally:
            # Cleanup
            s3_client.delete_object(Bucket=bucket_name, Key=key)

    def test_upload_metadata_json(self, s3_client, bucket_name, sample_metadata, test_prefix):
        """Test uploading metadata as JSON."""
        key = f"{test_prefix}/metadata/clinical_trials/2026/03/03/{sample_metadata['nct_id']}.json"

        try:
            s3_client.put_object(
                Bucket=bucket_name,
                Key=key,
                Body=json.dumps(sample_metadata).encode("utf-8"),
                ContentType="application/json",
            )

            # Verify
            response = s3_client.get_object(Bucket=bucket_name, Key=key)
            downloaded = json.loads(response["Body"].read().decode("utf-8"))

            assert downloaded["nct_id"] == sample_metadata["nct_id"]
        finally:
            s3_client.delete_object(Bucket=bucket_name, Key=key)

    def test_list_objects_with_prefix(self, s3_client, bucket_name, test_prefix):
        """Test listing objects with a prefix."""
        # Upload test objects
        test_keys = [
            f"{test_prefix}/raw/clinical_trials/test1.pdf",
            f"{test_prefix}/raw/clinical_trials/test2.pdf",
            f"{test_prefix}/metadata/test1.json",
        ]

        try:
            for key in test_keys:
                s3_client.put_object(Bucket=bucket_name, Key=key, Body=b"test content")

            # List with prefix
            response = s3_client.list_objects_v2(
                Bucket=bucket_name,
                Prefix=f"{test_prefix}/raw/",
            )
            keys = [obj["Key"] for obj in response.get("Contents", [])]

            assert len(keys) == 2
            assert f"{test_prefix}/raw/clinical_trials/test1.pdf" in keys
        finally:
            # Cleanup
            for key in test_keys:
                s3_client.delete_object(Bucket=bucket_name, Key=key)


class TestS3PathTemplates:
    """Test S3 path template rendering."""

    def test_raw_path_template(self, aws_s3_config, sample_metadata):
        """Test raw PDF path template."""
        paths = aws_s3_config["buckets"]["clinical-trials-pdfs"]["paths"]
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

    def test_metadata_path_template(self, aws_s3_config, sample_metadata):
        """Test metadata path template."""
        paths = aws_s3_config["buckets"]["clinical-trials-pdfs"]["paths"]
        template = paths["metadata"]

        rendered = template.format(
            source="clinical_trials",
            year="2026",
            month="03",
            day="03",
            nct_id=sample_metadata["nct_id"],
        )

        assert rendered == "metadata/clinical_trials/2026/03/03/NCT01234567.json"

    def test_manifests_path_template(self, aws_s3_config):
        """Test manifests path template."""
        paths = aws_s3_config["buckets"]["clinical-trials-pdfs"]["paths"]
        template = paths["manifests"]

        rendered = template.format(
            source="clinical_trials",
            run_id="run-12345",
        )

        assert rendered == "manifests/clinical_trials/run-12345.json"


class TestS3RetryConfiguration:
    """Test S3 retry configuration."""

    def test_retry_settings(self, aws_s3_config):
        """Verify retry configuration."""
        retry = aws_s3_config["retry"]
        assert retry["max_attempts"] == 3
        assert retry["backoff_factor"] == 1.5
        assert retry["jitter"] is True


class TestS3MultipartUpload:
    """Test S3 multipart upload configuration."""

    def test_multipart_settings(self, aws_s3_config):
        """Verify multipart upload settings."""
        multipart = aws_s3_config["multipart"]
        assert multipart["threshold_mb"] == 100
        assert multipart["chunk_size_mb"] == 10


class TestS3CostTracking:
    """Test S3 cost tracking configuration."""

    def test_cost_rates(self, aws_s3_config):
        """Verify cost rate configuration."""
        cost = aws_s3_config["cost"]
        assert cost["storage_per_gb"] == 0.023
        assert cost["glacier_per_gb"] == 0.004
        assert cost["put_requests"] == 0.005
        assert cost["get_requests"] == 0.0004

    def test_cost_tracking_enabled(self, aws_s3_config):
        """Verify cost tracking is enabled."""
        tracking = aws_s3_config["cost"]["tracking"]
        assert tracking["enabled"] is True
        assert tracking["tag_uploads"] is True
        assert tracking["tags"]["project"] == "multi-cloud-graphrag"
        assert tracking["tags"]["source"] == "clinical_trials"
        assert tracking["tags"]["environment"] == "production"


class TestS3LifecycleConfiguration:
    """Test S3 lifecycle configuration."""

    def test_lifecycle_rule_structure(self):
        """Verify lifecycle rule JSON structure."""
        lifecycle_rule = {
            "Rules": [
                {
                    "Id": "MoveToGlacier",
                    "Status": "Enabled",
                    "Prefix": "raw/",
                    "Transitions": [
                        {
                            "Days": 30,
                            "StorageClass": "GLACIER",
                        }
                    ],
                }
            ]
        }

        assert len(lifecycle_rule["Rules"]) == 1
        rule = lifecycle_rule["Rules"][0]
        assert rule["Status"] == "Enabled"
        assert rule["Prefix"] == "raw/"
        assert rule["Transitions"][0]["Days"] == 30
        assert rule["Transitions"][0]["StorageClass"] == "GLACIER"
