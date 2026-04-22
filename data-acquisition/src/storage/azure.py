"""
Azure Blob Storage provider - fully config-driven.

ALL configuration comes from YAML:
- container name
- connection string or SAS token
- prefix
- blob tier (Hot, Cool, Archive)
- encryption scope
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .base import BaseStorageProvider, StorageResult

logger = logging.getLogger(__name__)

# Lazy import azure-storage-blob to avoid requiring it if not using Azure
azure_storage_blob = None


class AzureBlobStorageProvider(BaseStorageProvider):
    """
    Azure Blob Storage provider.

    All configuration from YAML - nothing hardcoded.
    """

    def __init__(self, config: dict[str, Any]):
        """
        Initialize Azure provider with config.

        Config must include:
        - provider: "azure"
        - container: container name
        - connection_string: OR use account_name + account_key
        - prefix: optional blob prefix
        - blob_tier: optional tier (Hot, Cool, Archive)
        """
        super().__init__(config)
        self.provider_name = "azure_blob"

        # Validate required config
        self._validate_config()

        # ALL from config - no defaults
        self.container = config["container"]
        self.prefix = config.get("prefix", "")
        self.blob_tier = config.get("blob_tier")

        # Authentication from config
        self.connection_string = config.get("connection_string")
        self.account_name = config.get("account_name")
        self.account_key = config.get("account_key")
        self.sas_token = config.get("sas_token")

        self._client = None
        self._container_client = None

    def _validate_config(self) -> None:
        """Validate Azure-specific config."""
        if "container" not in self.config:
            raise ValueError(
                "Azure provider missing required config: container. "
                "ALL configuration must come from YAML."
            )

        # Check for valid auth config
        has_connection_string = bool(self.config.get("connection_string"))
        has_account_key = bool(self.config.get("account_name") and self.config.get("account_key"))
        has_sas_token = bool(self.config.get("account_name") and self.config.get("sas_token"))

        if not (has_connection_string or has_account_key or has_sas_token):
            raise ValueError(
                "Azure provider requires either: "
                "(1) connection_string, OR "
                "(2) account_name + account_key, OR "
                "(3) account_name + sas_token. "
                "ALL configuration must come from YAML."
            )

    async def initialize(self) -> None:
        """Initialize Azure Blob client."""
        global azure_storage_blob
        try:
            from azure.storage.blob import BlobServiceClient, ContainerClient
            azure_storage_blob = BlobServiceClient
        except ImportError:
            raise ImportError(
                "azure-storage-blob required for Azure storage. "
                "Install with: pip install azure-storage-blob"
            )

        # Build client from config
        if self.connection_string:
            self._client = azure_storage_blob.from_connection_string(
                self.connection_string
            )
        elif self.account_name and self.account_key:
            account_url = f"https://{self.account_name}.blob.core.windows.net"
            from azure.core.credentials import AzureNamedKeyCredential
            credential = AzureNamedKeyCredential(self.account_name, self.account_key)
            self._client = azure_storage_blob(account_url=account_url, credential=credential)
        elif self.account_name and self.sas_token:
            account_url = f"https://{self.account_name}.blob.core.windows.net"
            from azure.core.credentials import AzureSasCredential
            credential = AzureSasCredential(self.sas_token)
            self._client = azure_storage_blob(account_url=account_url, credential=credential)

        self._container_client = self._client.get_container_client(self.container)
        self._initialized = True

        logger.info(f"Azure provider initialized for container: {self.container}")

    async def store(
        self,
        file_path: Path,
        key: str,
        metadata: Optional[dict[str, Any]] = None,
        content_type: str = "application/octet-stream",
    ) -> StorageResult:
        """
        Store a file in Azure Blob Storage.

        ALL behavior from config (blob tier, etc.)
        """
        if not self._initialized:
            await self.initialize()

        # Build full blob name with prefix from config
        blob_name = f"{self.prefix}{key}" if self.prefix else key

        logger.info(f"Uploading to Azure Blob: {blob_name}")

        try:
            from azure.storage.blob import ContentSettings
            # Build upload options from config
            upload_options = {
                "content_settings": ContentSettings(content_type=content_type),
            }

            # Add blob tier from config
            if self.blob_tier:
                from azure.storage.blob import BlobTier
                tier_map = {
                    "Hot": BlobTier.Hot,
                    "Cool": BlobTier.Cool,
                    "Archive": BlobTier.Archive,
                }
                upload_options["blob_tier"] = tier_map.get(self.blob_tier, BlobTier.Hot)

            # Upload file — upload_blob() returns a BlobClient, not a properties dict
            with open(file_path, "rb") as data:
                blob_client = self._container_client.upload_blob(
                    name=blob_name,
                    data=data,
                    overwrite=True,
                    **upload_options,
                )

            file_size = file_path.stat().st_size
            props = blob_client.get_blob_properties()
            etag = props.etag.strip('"') if props.etag else ""

            logger.info(f"Uploaded {blob_name} ({file_size} bytes) to Azure Blob")

            return StorageResult(
                success=True,
                provider=self.provider_name,
                path=f"azure://{self.container}/{blob_name}",
                etag=etag,
                file_size_bytes=file_size,
            )

        except Exception as e:
            logger.error(f"Azure upload failed for {blob_name}: {e}")
            return StorageResult(
                success=False,
                provider=self.provider_name,
                path=blob_name,
                error=str(e),
            )

    async def retrieve(
        self, key: str, destination_path: Optional[Path] = None
    ) -> Optional[bytes]:
        """Retrieve a file from Azure Blob Storage."""
        if not self._initialized:
            await self.initialize()

        blob_name = f"{self.prefix}{key}" if self.prefix else key

        try:
            blob_client = self._container_client.get_blob_client(blob_name)
            data = blob_client.download_blob().readall()

            if destination_path:
                destination_path.write_bytes(data)
                logger.info(f"Downloaded {blob_name} to {destination_path}")

            return data

        except Exception as e:
            logger.error(f"Azure retrieve failed for {blob_name}: {e}")
            return None

    async def exists(self, key: str) -> bool:
        """Check if blob exists in Azure storage."""
        if not self._initialized:
            await self.initialize()

        blob_name = f"{self.prefix}{key}" if self.prefix else key

        try:
            blob_client = self._container_client.get_blob_client(blob_name)
            return blob_client.exists()
        except Exception as e:
            logger.error(f"Azure exists check failed for {blob_name}: {e}")
            return False

    async def delete(self, key: str) -> bool:
        """Delete a blob from Azure storage."""
        if not self._initialized:
            await self.initialize()

        blob_name = f"{self.prefix}{key}" if self.prefix else key

        try:
            self._container_client.delete_blob(blob_name)
            logger.info(f"Deleted {blob_name} from Azure Blob")
            return True
        except Exception as e:
            logger.error(f"Azure delete failed for {blob_name}: {e}")
            return False

    async def store_metadata(self, key: str, metadata: dict[str, Any]) -> StorageResult:
        """Store metadata as JSON sidecar in Azure Blob Storage."""
        if not self._initialized:
            await self.initialize()

        metadata_key = self._generate_metadata_key(key)
        blob_name = f"{self.prefix}{metadata_key}" if self.prefix else metadata_key

        logger.info(f"Uploading metadata to Azure Blob: {blob_name}")

        try:
            # Add metadata timestamp from config convention
            metadata["_stored_at"] = datetime.utcnow().isoformat()
            metadata["_storage_provider"] = self.provider_name

            metadata_json = json.dumps(metadata, indent=2)

            from azure.storage.blob import ContentSettings
            upload_options = {
                "content_settings": ContentSettings(content_type="application/json"),
            }

            if self.blob_tier:
                from azure.storage.blob import BlobTier
                tier_map = {
                    "Hot": BlobTier.Hot,
                    "Cool": BlobTier.Cool,
                    "Archive": BlobTier.Archive,
                }
                upload_options["blob_tier"] = tier_map.get(self.blob_tier, BlobTier.Hot)

            self._container_client.upload_blob(
                name=blob_name,
                data=metadata_json.encode("utf-8"),
                overwrite=True,
                **upload_options,
            )

            logger.info(f"Uploaded metadata to {blob_name}")

            return StorageResult(
                success=True,
                provider=self.provider_name,
                path=f"azure://{self.container}/{blob_name}",
                metadata_path=f"azure://{self.container}/{blob_name}",
            )

        except Exception as e:
            logger.error(f"Azure metadata upload failed for {blob_name}: {e}")
            return StorageResult(
                success=False,
                provider=self.provider_name,
                path=blob_name,
                error=str(e),
            )

    async def close(self) -> None:
        """Close Azure clients."""
        if self._container_client:
            # Azure clients don't need explicit closing
            self._container_client = None
            self._client = None
            logger.debug("Azure clients closed")
