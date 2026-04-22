"""
Storage test utilities and helpers.

Provides utility functions for storage testing across AWS, Azure, and local providers.
"""

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import boto3
from azure.storage.blob import BlobServiceClient, ContainerClient
from botocore.exceptions import ClientError


@dataclass
class StorageTestResult:
    """Result of a storage operation test."""

    provider: str
    operation: str
    success: bool
    duration_ms: float
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StorageTestReport:
    """Aggregated report of storage tests."""

    timestamp: str
    total_tests: int
    passed: int
    failed: int
    results: List[StorageTestResult] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        """Calculate pass rate percentage."""
        if self.total_tests == 0:
            return 0.0
        return (self.passed / self.total_tests) * 100

    def to_dict(self) -> Dict[str, Any]:
        """Convert report to dictionary."""
        return {
            "timestamp": self.timestamp,
            "summary": {
                "total": self.total_tests,
                "passed": self.passed,
                "failed": self.failed,
                "pass_rate": self.pass_rate,
            },
            "results": [
                {
                    "provider": r.provider,
                    "operation": r.operation,
                    "success": r.success,
                    "duration_ms": r.duration_ms,
                    "error": r.error,
                }
                for r in self.results
            ],
        }


class StorageTestUtils:
    """Utility class for storage testing."""

    def __init__(self):
        self.results: List[StorageTestResult] = []

    def time_operation(self, func, *args, **kwargs) -> tuple[Any, float]:
        """Execute a function and return result with duration in milliseconds."""
        start = time.perf_counter()
        try:
            result = func(*args, **kwargs)
            duration = (time.perf_counter() - start) * 1000
            return result, duration
        except Exception as e:
            duration = (time.perf_counter() - start) * 1000
            raise

    def calculate_md5(self, content: bytes) -> str:
        """Calculate MD5 hash of content."""
        return hashlib.md5(content).hexdigest()

    def generate_test_key(self, prefix: str, extension: str = "pdf") -> str:
        """Generate a unique test key."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{prefix}/{timestamp}_test.{extension}"

    def create_test_metadata(self, nct_id: Optional[str] = None) -> Dict[str, Any]:
        """Create test metadata for a clinical trial."""
        return {
            "nct_id": nct_id or f"NCT{int(time.time()) % 100000000:08d}",
            "brief_title": "Test Clinical Trial",
            "overall_status": "Recruiting",
            "lead_sponsor_name": "Test Hospital",
            "study_type": "Interventional",
            "phase": "Phase 3",
            "enrollment_count": 100,
            "last_update_post_date": datetime.now().strftime("%Y-%m-%d"),
            "fetched_at": datetime.now().isoformat() + "Z",
            "source_version": "1.0",
            "pdf_type": "protocol",
        }


class AWSTestClient:
    """Test client for AWS S3 operations."""

    def __init__(self, profile: str, region: str, bucket: str):
        self.profile = profile
        self.region = region
        self.bucket = bucket
        self.client = None
        self._initialized = False

    def _get_client(self):
        """Lazy initialization of S3 client."""
        if not self._initialized:
            try:
                session = boto3.Session(profile_name=self.profile)
                self.client = session.client("s3", region_name=self.region)
                self._initialized = True
            except Exception:
                self._initialized = False
        return self.client

    @property
    def is_available(self) -> bool:
        """Check if AWS S3 is available."""
        return self._get_client() is not None

    def upload_object(self, key: str, content: bytes, content_type: str = "application/pdf") -> StorageTestResult:
        """Upload an object to S3."""
        client = self._get_client()
        if not client:
            return StorageTestResult(
                provider="aws",
                operation="upload",
                success=False,
                duration_ms=0,
                error="Client not available",
            )

        start = time.perf_counter()
        try:
            client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=content,
                ContentType=content_type,
            )
            duration = (time.perf_counter() - start) * 1000
            return StorageTestResult(
                provider="aws",
                operation="upload",
                success=True,
                duration_ms=duration,
                metadata={"key": key, "size": len(content)},
            )
        except Exception as e:
            duration = (time.perf_counter() - start) * 1000
            return StorageTestResult(
                provider="aws",
                operation="upload",
                success=False,
                duration_ms=duration,
                error=str(e),
            )

    def download_object(self, key: str) -> StorageTestResult:
        """Download an object from S3."""
        client = self._get_client()
        if not client:
            return StorageTestResult(
                provider="aws",
                operation="download",
                success=False,
                duration_ms=0,
                error="Client not available",
            )

        start = time.perf_counter()
        try:
            response = client.get_object(Bucket=self.bucket, Key=key)
            content = response["Body"].read()
            duration = (time.perf_counter() - start) * 1000
            return StorageTestResult(
                provider="aws",
                operation="download",
                success=True,
                duration_ms=duration,
                metadata={"key": key, "size": len(content)},
            )
        except Exception as e:
            duration = (time.perf_counter() - start) * 1000
            return StorageTestResult(
                provider="aws",
                operation="download",
                success=False,
                duration_ms=duration,
                error=str(e),
            )

    def delete_object(self, key: str) -> StorageTestResult:
        """Delete an object from S3."""
        client = self._get_client()
        if not client:
            return StorageTestResult(
                provider="aws",
                operation="delete",
                success=False,
                duration_ms=0,
                error="Client not available",
            )

        start = time.perf_counter()
        try:
            client.delete_object(Bucket=self.bucket, Key=key)
            duration = (time.perf_counter() - start) * 1000
            return StorageTestResult(
                provider="aws",
                operation="delete",
                success=True,
                duration_ms=duration,
                metadata={"key": key},
            )
        except Exception as e:
            duration = (time.perf_counter() - start) * 1000
            return StorageTestResult(
                provider="aws",
                operation="delete",
                success=False,
                duration_ms=duration,
                error=str(e),
            )

    def list_objects(self, prefix: str = "") -> StorageTestResult:
        """List objects in S3 bucket."""
        client = self._get_client()
        if not client:
            return StorageTestResult(
                provider="aws",
                operation="list",
                success=False,
                duration_ms=0,
                error="Client not available",
            )

        start = time.perf_counter()
        try:
            response = client.list_objects_v2(Bucket=self.bucket, Prefix=prefix)
            objects = response.get("Contents", [])
            duration = (time.perf_counter() - start) * 1000
            return StorageTestResult(
                provider="aws",
                operation="list",
                success=True,
                duration_ms=duration,
                metadata={"prefix": prefix, "count": len(objects)},
            )
        except Exception as e:
            duration = (time.perf_counter() - start) * 1000
            return StorageTestResult(
                provider="aws",
                operation="list",
                success=False,
                duration_ms=duration,
                error=str(e),
            )


class AzureTestClient:
    """Test client for Azure Blob operations."""

    def __init__(self, connection_string: str, container: str):
        self.connection_string = connection_string
        self.container = container
        self.client = None
        self._initialized = False

    def _get_client(self) -> Optional[ContainerClient]:
        """Lazy initialization of container client."""
        if not self._initialized:
            try:
                if not self.connection_string:
                    self._initialized = False
                    return None
                blob_service_client = BlobServiceClient.from_connection_string(self.connection_string)
                self.client = blob_service_client.get_container_client(self.container)
                self._initialized = True
            except Exception:
                self._initialized = False
        return self.client

    @property
    def is_available(self) -> bool:
        """Check if Azure Blob is available."""
        return self._get_client() is not None

    def upload_blob(self, blob_name: str, content: bytes, content_type: str = "application/pdf") -> StorageTestResult:
        """Upload a blob to Azure."""
        client = self._get_client()
        if not client:
            return StorageTestResult(
                provider="azure",
                operation="upload",
                success=False,
                duration_ms=0,
                error="Client not available",
            )

        start = time.perf_counter()
        try:
            blob_client = client.get_blob_client(blob_name)
            blob_client.upload_blob(content, overwrite=True, content_settings={"content_type": content_type})
            duration = (time.perf_counter() - start) * 1000
            return StorageTestResult(
                provider="azure",
                operation="upload",
                success=True,
                duration_ms=duration,
                metadata={"blob_name": blob_name, "size": len(content)},
            )
        except Exception as e:
            duration = (time.perf_counter() - start) * 1000
            return StorageTestResult(
                provider="azure",
                operation="upload",
                success=False,
                duration_ms=duration,
                error=str(e),
            )

    def download_blob(self, blob_name: str) -> StorageTestResult:
        """Download a blob from Azure."""
        client = self._get_client()
        if not client:
            return StorageTestResult(
                provider="azure",
                operation="download",
                success=False,
                duration_ms=0,
                error="Client not available",
            )

        start = time.perf_counter()
        try:
            blob_client = client.get_blob_client(blob_name)
            content = blob_client.download_blob().readall()
            duration = (time.perf_counter() - start) * 1000
            return StorageTestResult(
                provider="azure",
                operation="download",
                success=True,
                duration_ms=duration,
                metadata={"blob_name": blob_name, "size": len(content)},
            )
        except Exception as e:
            duration = (time.perf_counter() - start) * 1000
            return StorageTestResult(
                provider="azure",
                operation="download",
                success=False,
                duration_ms=duration,
                error=str(e),
            )

    def delete_blob(self, blob_name: str) -> StorageTestResult:
        """Delete a blob from Azure."""
        client = self._get_client()
        if not client:
            return StorageTestResult(
                provider="azure",
                operation="delete",
                success=False,
                duration_ms=0,
                error="Client not available",
            )

        start = time.perf_counter()
        try:
            blob_client = client.get_blob_client(blob_name)
            blob_client.delete_blob()
            duration = (time.perf_counter() - start) * 1000
            return StorageTestResult(
                provider="azure",
                operation="delete",
                success=True,
                duration_ms=duration,
                metadata={"blob_name": blob_name},
            )
        except Exception as e:
            duration = (time.perf_counter() - start) * 1000
            return StorageTestResult(
                provider="azure",
                operation="delete",
                success=False,
                duration_ms=duration,
                error=str(e),
            )

    def list_blobs(self, name_starts_with: str = "") -> StorageTestResult:
        """List blobs in container."""
        client = self._get_client()
        if not client:
            return StorageTestResult(
                provider="azure",
                operation="list",
                success=False,
                duration_ms=0,
                error="Client not available",
            )

        start = time.perf_counter()
        try:
            blobs = list(client.list_blobs(name_starts_with=name_starts_with))
            duration = (time.perf_counter() - start) * 1000
            return StorageTestResult(
                provider="azure",
                operation="list",
                success=True,
                duration_ms=duration,
                metadata={"prefix": name_starts_with, "count": len(blobs)},
            )
        except Exception as e:
            duration = (time.perf_counter() - start) * 1000
            return StorageTestResult(
                provider="azure",
                operation="list",
                success=False,
                duration_ms=duration,
                error=str(e),
            )


class LocalTestClient:
    """Test client for local filesystem operations."""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    @property
    def is_available(self) -> bool:
        """Check if local storage is available."""
        return self.base_dir.exists()

    def upload_file(self, relative_path: str, content: bytes) -> StorageTestResult:
        """Upload a file to local storage."""
        start = time.perf_counter()
        try:
            file_path = self.base_dir / relative_path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(content)
            duration = (time.perf_counter() - start) * 1000
            return StorageTestResult(
                provider="local",
                operation="upload",
                success=True,
                duration_ms=duration,
                metadata={"path": str(file_path), "size": len(content)},
            )
        except Exception as e:
            duration = (time.perf_counter() - start) * 1000
            return StorageTestResult(
                provider="local",
                operation="upload",
                success=False,
                duration_ms=duration,
                error=str(e),
            )

    def download_file(self, relative_path: str) -> StorageTestResult:
        """Download a file from local storage."""
        start = time.perf_counter()
        try:
            file_path = self.base_dir / relative_path
            content = file_path.read_bytes()
            duration = (time.perf_counter() - start) * 1000
            return StorageTestResult(
                provider="local",
                operation="download",
                success=True,
                duration_ms=duration,
                metadata={"path": str(file_path), "size": len(content)},
            )
        except Exception as e:
            duration = (time.perf_counter() - start) * 1000
            return StorageTestResult(
                provider="local",
                operation="download",
                success=False,
                duration_ms=duration,
                error=str(e),
            )

    def delete_file(self, relative_path: str) -> StorageTestResult:
        """Delete a file from local storage."""
        start = time.perf_counter()
        try:
            file_path = self.base_dir / relative_path
            if file_path.exists():
                file_path.unlink()
            duration = (time.perf_counter() - start) * 1000
            return StorageTestResult(
                provider="local",
                operation="delete",
                success=True,
                duration_ms=duration,
                metadata={"path": str(file_path)},
            )
        except Exception as e:
            duration = (time.perf_counter() - start) * 1000
            return StorageTestResult(
                provider="local",
                operation="delete",
                success=False,
                duration_ms=duration,
                error=str(e),
            )

    def list_files(self, pattern: str = "**/*") -> StorageTestResult:
        """List files in local storage."""
        start = time.perf_counter()
        try:
            files = list(self.base_dir.glob(pattern))
            duration = (time.perf_counter() - start) * 1000
            return StorageTestResult(
                provider="local",
                operation="list",
                success=True,
                duration_ms=duration,
                metadata={"pattern": pattern, "count": len(files)},
            )
        except Exception as e:
            duration = (time.perf_counter() - start) * 1000
            return StorageTestResult(
                provider="local",
                operation="list",
                success=False,
                duration_ms=duration,
                error=str(e),
            )


def create_test_report(results: List[StorageTestResult]) -> StorageTestReport:
    """Create a test report from results."""
    passed = sum(1 for r in results if r.success)
    return StorageTestReport(
        timestamp=datetime.now().isoformat() + "Z",
        total_tests=len(results),
        passed=passed,
        failed=len(results) - passed,
        results=results,
    )
