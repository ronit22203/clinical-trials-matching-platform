"""
Storage module for multi-cloud PDF and metadata storage.

Provides:
- Base storage interface
- AWS S3 provider
- Azure Blob provider
- Multi-cloud manager with automatic fallback
"""

from .base import BaseStorageProvider, StorageResult
from .aws import S3StorageProvider
from .azure import AzureBlobStorageProvider
from .local import LocalStorageProvider
from .manager import MultiCloudStorageManager

__all__ = [
    "BaseStorageProvider",
    "StorageResult",
    "S3StorageProvider",
    "AzureBlobStorageProvider",
    "LocalStorageProvider",
    "MultiCloudStorageManager",
]
