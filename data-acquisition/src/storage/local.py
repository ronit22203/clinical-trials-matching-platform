"""
Local filesystem storage provider - fully config-driven.

ALL configuration comes from config/app.yaml → data_acquisition.storage.local_fallback:
- paths.base_dir: root directory for stored files
- paths.raw / metadata / manifests: path templates (for key generation reference)
- retention_days: how long to retain files before cleanup
- cleanup.enabled / min_free_space_gb: cleanup settings
- metrics.track_disk_usage / track_file_count / alert_at_percent: observability
"""

import json
import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from .base import BaseStorageProvider, StorageResult

logger = logging.getLogger(__name__)


class LocalStorageProvider(BaseStorageProvider):
    """
    Local filesystem storage provider (catastrophic fallback).

    All configuration from YAML - nothing hardcoded.
    """

    def __init__(self, config: dict[str, Any]):
        """
        Initialize local provider with config from local_fallback.yml.

        Config must include:
        - paths.base_dir: root directory
        - paths.raw / metadata / manifests: path templates
        - retention_days: file retention period in days
        """
        super().__init__(config)
        self.provider_name = "local"

        self._validate_config()

        # ALL from config - no defaults
        paths_config = config["paths"]
        self.base_dir = Path(paths_config["base_dir"])
        self.raw_template: str = paths_config["raw"]
        self.metadata_template: str = paths_config["metadata"]
        self.manifests_template: str = paths_config["manifests"]

        self.retention_days: int = config["retention_days"]

        cleanup_config = config.get("cleanup", {})
        self.cleanup_enabled: bool = cleanup_config.get("enabled", False)
        self.min_free_space_gb: Optional[float] = cleanup_config.get("min_free_space_gb")

        metrics_config = config.get("metrics", {})
        self.track_disk_usage: bool = metrics_config.get("track_disk_usage", False)
        self.track_file_count: bool = metrics_config.get("track_file_count", False)
        self.alert_at_percent: Optional[int] = metrics_config.get("alert_at_percent")

    def _validate_config(self) -> None:
        """Validate local-specific config."""
        paths_config = self.config.get("paths", {})
        required_paths = ["base_dir", "raw", "metadata", "manifests"]
        missing_paths = [p for p in required_paths if p not in paths_config]
        if missing_paths:
            raise ValueError(
                f"Local provider missing required paths config: {missing_paths}. "
                "ALL configuration must come from YAML."
            )
        if "retention_days" not in self.config:
            raise ValueError(
                "Local provider missing required config: retention_days. "
                "ALL configuration must come from YAML."
            )

    def resolve_path_template(self, template: str, **kwargs: str) -> str:
        """
        Resolve a path template from config (e.g. paths.raw) with runtime values.

        Template variables: {base_dir}, {source}, {year}, {month}, {day}, {nct_id}, etc.
        """
        resolved = template.replace("{base_dir}", str(self.base_dir))
        for key, value in kwargs.items():
            resolved = resolved.replace(f"{{{key}}}", value)
        return resolved

    async def initialize(self) -> None:
        """Initialize by creating base directory."""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._initialized = True
        logger.info(f"Local provider initialized at: {self.base_dir}")

    async def store(
        self,
        file_path: Path,
        key: str,
        metadata: Optional[dict[str, Any]] = None,
        content_type: str = "application/octet-stream",
    ) -> StorageResult:
        """Store a file in the local filesystem under base_dir / key."""
        if not self._initialized:
            await self.initialize()

        dest = self.base_dir / key
        dest.parent.mkdir(parents=True, exist_ok=True)

        logger.info(f"Storing locally: {dest}")

        try:
            shutil.copy2(file_path, dest)
            file_size = dest.stat().st_size

            logger.info(f"Stored {key} ({file_size} bytes) locally")

            return StorageResult(
                success=True,
                provider=self.provider_name,
                path=str(dest),
                file_size_bytes=file_size,
            )

        except Exception as e:
            logger.error(f"Local store failed for {key}: {e}")
            return StorageResult(
                success=False,
                provider=self.provider_name,
                path=str(dest),
                error=str(e),
            )

    async def retrieve(
        self, key: str, destination_path: Optional[Path] = None
    ) -> Optional[bytes]:
        """Retrieve a file from the local filesystem."""
        if not self._initialized:
            await self.initialize()

        source = self.base_dir / key

        try:
            data = source.read_bytes()

            if destination_path:
                destination_path.write_bytes(data)
                logger.info(f"Retrieved {key} to {destination_path}")

            return data

        except Exception as e:
            logger.error(f"Local retrieve failed for {key}: {e}")
            return None

    async def exists(self, key: str) -> bool:
        """Check if a file exists in local storage."""
        if not self._initialized:
            await self.initialize()

        return (self.base_dir / key).exists()

    async def delete(self, key: str) -> bool:
        """Delete a file from local storage."""
        if not self._initialized:
            await self.initialize()

        target = self.base_dir / key

        try:
            target.unlink()
            logger.info(f"Deleted {key} from local storage")
            return True
        except Exception as e:
            logger.error(f"Local delete failed for {key}: {e}")
            return False

    async def store_metadata(self, key: str, metadata: dict[str, Any]) -> StorageResult:
        """Store metadata as a JSON sidecar in the local filesystem."""
        if not self._initialized:
            await self.initialize()

        metadata_key = self._generate_metadata_key(key)
        dest = self.base_dir / metadata_key
        dest.parent.mkdir(parents=True, exist_ok=True)

        logger.info(f"Storing metadata locally: {dest}")

        try:
            metadata["_stored_at"] = datetime.utcnow().isoformat()
            metadata["_storage_provider"] = self.provider_name

            dest.write_text(json.dumps(metadata, indent=2))

            logger.info(f"Stored metadata at {dest}")

            return StorageResult(
                success=True,
                provider=self.provider_name,
                path=str(dest),
                metadata_path=str(dest),
            )

        except Exception as e:
            logger.error(f"Local metadata store failed for {key}: {e}")
            return StorageResult(
                success=False,
                provider=self.provider_name,
                path=str(dest),
                error=str(e),
            )

    def cleanup_expired(self) -> int:
        """
        Remove files older than retention_days (from config).

        Only runs if cleanup.enabled is true in local_fallback.yml.

        Returns:
            Number of files removed.
        """
        if not self.cleanup_enabled:
            logger.debug("Local cleanup disabled in config (cleanup.enabled: false)")
            return 0

        cutoff = datetime.utcnow() - timedelta(days=self.retention_days)
        removed = 0

        for file_path in self.base_dir.rglob("*"):
            if file_path.is_file():
                mtime = datetime.utcfromtimestamp(file_path.stat().st_mtime)
                if mtime < cutoff:
                    try:
                        file_path.unlink()
                        removed += 1
                    except Exception as e:
                        logger.warning(f"Failed to remove expired file {file_path}: {e}")

        logger.info(
            f"Cleanup complete: removed {removed} files older than {self.retention_days} days"
        )
        return removed

    def get_disk_usage(self) -> dict[str, Any]:
        """
        Return disk usage stats.

        Only collects metrics enabled in local_fallback.yml
        (metrics.track_disk_usage, metrics.track_file_count, metrics.alert_at_percent).
        """
        if not self.track_disk_usage:
            return {}

        total_bytes = sum(
            f.stat().st_size for f in self.base_dir.rglob("*") if f.is_file()
        )

        stats: dict[str, Any] = {
            "base_dir": str(self.base_dir),
            "total_bytes": total_bytes,
            "total_gb": round(total_bytes / (1024**3), 4),
        }

        if self.track_file_count:
            stats["file_count"] = sum(1 for f in self.base_dir.rglob("*") if f.is_file())

        if self.min_free_space_gb is not None:
            usage = shutil.disk_usage(self.base_dir)
            free_gb = usage.free / (1024**3)
            stats["free_gb"] = round(free_gb, 3)
            stats["low_disk_alert"] = free_gb < self.min_free_space_gb

        if self.alert_at_percent is not None:
            usage = shutil.disk_usage(self.base_dir)
            used_percent = (usage.used / usage.total) * 100
            stats["used_percent"] = round(used_percent, 1)
            stats["usage_alert"] = used_percent >= self.alert_at_percent

        return stats
