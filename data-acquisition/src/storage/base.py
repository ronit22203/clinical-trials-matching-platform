"""
Base storage provider abstract class.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class StorageResult:
    """Result of a storage operation."""

    success: bool
    provider: str
    path: str
    etag: Optional[str] = None
    error: Optional[str] = None
    metadata_path: Optional[str] = None
    stored_at: datetime = field(default_factory=datetime.utcnow)
    file_size_bytes: int = 0
    fallback_chain: list[str] = field(default_factory=list)


class BaseStorageProvider(ABC):
    """
    Abstract base class for storage providers.

    Each cloud provider (AWS S3, Azure Blob, etc.) implements this interface.
    """

    def __init__(self, config: dict[str, Any]):
        """
        Initialize storage provider with configuration.

        Args:
            config: Provider-specific configuration dictionary
        """
        self.config = config
        self.provider_name = config.get("provider", "unknown")
        self._initialized = False

    @abstractmethod
    async def initialize(self) -> None:
        """
        Initialize the storage client (connections, credentials, etc.).

        Should be called before any store/retrieve operations.
        """
        pass

    @abstractmethod
    async def store(
        self,
        file_path: Path,
        key: str,
        metadata: Optional[dict[str, Any]] = None,
        content_type: str = "application/octet-stream",
    ) -> StorageResult:
        """
        Store a file in the cloud storage.

        Args:
            file_path: Path to the local file to upload
            key: Storage key/path for the file
            metadata: Optional metadata to store alongside the file
            content_type: MIME type of the file

        Returns:
            StorageResult indicating success/failure
        """
        pass

    @abstractmethod
    async def retrieve(
        self, key: str, destination_path: Optional[Path] = None
    ) -> Optional[bytes]:
        """
        Retrieve a file from cloud storage.

        Args:
            key: Storage key/path for the file
            destination_path: Optional path to save the file locally

        Returns:
            File contents as bytes, or None if failed
        """
        pass

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """
        Check if a file exists in storage.

        Args:
            key: Storage key/path for the file

        Returns:
            True if file exists, False otherwise
        """
        pass

    @abstractmethod
    async def delete(self, key: str) -> bool:
        """
        Delete a file from storage.

        Args:
            key: Storage key/path for the file

        Returns:
            True if deleted successfully, False otherwise
        """
        pass

    @abstractmethod
    async def store_metadata(self, key: str, metadata: dict[str, Any]) -> StorageResult:
        """
        Store metadata as a sidecar file.

        Args:
            key: Base key for the metadata (will be stored as key.json)
            metadata: Metadata dictionary to store

        Returns:
            StorageResult indicating success/failure
        """
        pass

    async def close(self) -> None:
        """
        Clean up resources (close connections, etc.).

        Should be called when the provider is no longer needed.
        """
        pass

    def _generate_metadata_key(self, key: str) -> str:
        """Generate metadata sidecar key from file key."""
        # Remove extension if present and add .json
        base_key = key.rsplit(".", 1)[0] if "." in key.split("/")[-1] else key
        return f"{base_key}.metadata.json"

    @property
    def bucket_or_container(self) -> str:
        """Get the bucket or container name from config."""
        return self.config.get("bucket") or self.config.get("container", "")
