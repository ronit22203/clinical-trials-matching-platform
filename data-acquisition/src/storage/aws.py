"""
AWS S3 storage provider - fully config-driven.

ALL configuration comes from YAML:
- bucket name
- region
- credentials (from env or config)
- prefixes
- storage class
- encryption settings
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .base import BaseStorageProvider, StorageResult

logger = logging.getLogger(__name__)

# Lazy import boto3 to avoid requiring it if not using AWS
boto3 = None


class S3StorageProvider(BaseStorageProvider):
    """
    AWS S3 storage provider.

    All configuration from YAML - nothing hardcoded.
    """

    def __init__(self, config: dict[str, Any]):
        """
        Initialize S3 provider with config.

        Config must include:
        - provider: "aws"
        - bucket: bucket name
        - region: AWS region
        - prefix: optional key prefix
        - storage_class: optional storage class (STANDARD, GLACIER, etc.)
        - encryption: optional encryption config
        """
        super().__init__(config)
        self.provider_name = "aws_s3"

        # Validate required config
        self._validate_config()

        # ALL from config - no defaults
        self.bucket = config["bucket"]
        self.region = config["region"]
        self.prefix = config.get("prefix", "")
        self.storage_class = config.get("storage_class")
        self.encryption = config.get("encryption")
        self.profile = config.get("profile")  # AWS named profile from aws_s3.yml

        # Probe profile availability at init time — fall back to env vars if missing
        if self.profile:
            try:
                import boto3 as _b
                _b.Session(profile_name=self.profile).get_credentials()
            except Exception:
                logger.warning(
                    f"AWS profile '{self.profile}' not found — falling back to env vars / instance role"
                )
                self.profile = None

        # Explicit credentials from config (optional; profile or env vars take precedence)
        self.access_key = config.get("credentials", {}).get("access_key")
        self.secret_key = config.get("credentials", {}).get("secret_key")

        self._client = None

    def _validate_config(self) -> None:
        """Validate S3-specific config."""
        required = ["bucket", "region"]
        missing = [k for k in required if k not in self.config]
        if missing:
            raise ValueError(
                f"S3 provider missing required config: {missing}. "
                "ALL configuration must come from YAML."
            )

    async def initialize(self) -> None:
        """Initialize boto3 S3 client."""
        global boto3
        try:
            import boto3
        except ImportError:
            raise ImportError(
                "boto3 required for S3 storage. Install with: pip install boto3"
            )

        # Build client config from YAML
        import boto3 as _boto3
        # Use named profile if available (resolved at __init__ time), else env vars / instance role
        session = _boto3.Session(
            profile_name=self.profile,
            region_name=self.region,
        ) if self.profile else _boto3.Session(region_name=self.region)

        session_kwargs: dict[str, Any] = {}
        if self.access_key and self.secret_key:
            session_kwargs["aws_access_key_id"] = self.access_key
            session_kwargs["aws_secret_access_key"] = self.secret_key

        self._client = session.client("s3", **session_kwargs)
        self._initialized = True

        logger.info(f"S3 provider initialized for bucket: {self.bucket}")

    async def store(
        self,
        file_path: Path,
        key: str,
        metadata: Optional[dict[str, Any]] = None,
        content_type: str = "application/octet-stream",
    ) -> StorageResult:
        """
        Store a file in S3.

        ALL behavior from config (storage class, encryption, etc.)
        """
        if not self._initialized:
            await self.initialize()

        # Build full key with prefix from config
        full_key = f"{self.prefix}{key}" if self.prefix else key

        logger.info(f"Uploading to S3: {full_key}")

        try:
            # Build upload args from config
            extra_args: dict = {"ContentType": content_type}

            # Add storage class from config
            if self.storage_class:
                extra_args["StorageClass"] = self.storage_class

            # Add encryption from config
            if self.encryption:
                if self.encryption.get("sse_algorithm"):
                    extra_args["ServerSideEncryption"] = self.encryption[
                        "sse_algorithm"
                    ]
                if self.encryption.get("kms_key_id"):
                    extra_args["SSEKMSKeyId"] = self.encryption["kms_key_id"]

            # Upload file
            with open(file_path, "rb") as f:
                response = self._client.upload_fileobj(f, self.bucket, full_key, ExtraArgs=extra_args)

            # Get ETag
            head_response = self._client.head_object(Bucket=self.bucket, Key=full_key)
            etag = head_response.get("ETag", "").strip('"')

            file_size = file_path.stat().st_size

            logger.info(f"Uploaded {full_key} ({file_size} bytes) to S3")

            return StorageResult(
                success=True,
                provider=self.provider_name,
                path=f"s3://{self.bucket}/{full_key}",
                etag=etag,
                file_size_bytes=file_size,
            )

        except Exception as e:
            logger.error(f"S3 upload failed for {full_key}: {e}")
            return StorageResult(
                success=False,
                provider=self.provider_name,
                path=full_key,
                error=str(e),
            )

    async def retrieve(
        self, key: str, destination_path: Optional[Path] = None
    ) -> Optional[bytes]:
        """Retrieve a file from S3."""
        if not self._initialized:
            await self.initialize()

        full_key = f"{self.prefix}{key}" if self.prefix else key

        try:
            response = self._client.get_object(Bucket=self.bucket, Key=full_key)
            data = response["Body"].read()

            if destination_path:
                destination_path.write_bytes(data)
                logger.info(f"Downloaded {full_key} to {destination_path}")

            return data

        except Exception as e:
            logger.error(f"S3 retrieve failed for {full_key}: {e}")
            return None

    async def exists(self, key: str) -> bool:
        """Check if file exists in S3."""
        if not self._initialized:
            await self.initialize()

        full_key = f"{self.prefix}{key}" if self.prefix else key

        try:
            self._client.head_object(Bucket=self.bucket, Key=full_key)
            return True
        except self._client.exceptions.ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return False
            raise

    async def delete(self, key: str) -> bool:
        """Delete a file from S3."""
        if not self._initialized:
            await self.initialize()

        full_key = f"{self.prefix}{key}" if self.prefix else key

        try:
            self._client.delete_object(Bucket=self.bucket, Key=full_key)
            logger.info(f"Deleted {full_key} from S3")
            return True
        except Exception as e:
            logger.error(f"S3 delete failed for {full_key}: {e}")
            return False

    async def store_metadata(self, key: str, metadata: dict[str, Any]) -> StorageResult:
        """Store metadata as JSON sidecar in S3."""
        if not self._initialized:
            await self.initialize()

        metadata_key = self._generate_metadata_key(key)
        full_key = f"{self.prefix}{metadata_key}" if self.prefix else metadata_key

        logger.info(f"Uploading metadata to S3: {full_key}")

        try:
            # Add metadata timestamp from config convention
            metadata["_stored_at"] = datetime.utcnow().isoformat()
            metadata["_storage_provider"] = self.provider_name

            metadata_json = json.dumps(metadata, indent=2)

            put_kwargs = {
                "Bucket": self.bucket,
                "Key": full_key,
                "ContentType": "application/json",
            }

            if self.storage_class:
                put_kwargs["StorageClass"] = self.storage_class

            self._client.put_object(Body=metadata_json.encode("utf-8"), **put_kwargs)

            logger.info(f"Uploaded metadata to {full_key}")

            return StorageResult(
                success=True,
                provider=self.provider_name,
                path=f"s3://{self.bucket}/{full_key}",
                metadata_path=f"s3://{self.bucket}/{full_key}",
            )

        except Exception as e:
            logger.error(f"S3 metadata upload failed for {full_key}: {e}")
            return StorageResult(
                success=False,
                provider=self.provider_name,
                path=full_key,
                error=str(e),
            )

    async def close(self) -> None:
        """Close S3 client."""
        if self._client:
            # boto3 clients don't need explicit closing
            self._client = None
            logger.debug("S3 client closed")
