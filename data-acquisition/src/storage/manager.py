"""
Multi-cloud storage manager with automatic fallback.

ALL configuration comes from config/app.yaml:
- data_acquisition.storage.providers      → chain order, failover_on errors, max_consecutive_failures, routing keys
- data_acquisition.storage.aws_s3         → bucket name, region, profile, retry, encryption
- data_acquisition.storage.azure_blob     → container name, connection_string, retry
- data_acquisition.storage.local_fallback → paths, retention_days, cleanup, metrics

Provider chain: S3 (priority 1) → Azure Blob (priority 2) → Local (priority 99)

Each provider is retried up to its own retry.max_attempts (from its YAML) with backoff
before failing over to the next provider. The fallback_chain list on StorageResult
records every provider that was attempted before success (or exhaustion).
"""

import asyncio
import logging
import os
import random
from pathlib import Path
from typing import Any, Optional

from .aws import S3StorageProvider
from .azure import AzureBlobStorageProvider
from .base import BaseStorageProvider, StorageResult
from .local import LocalStorageProvider

logger = logging.getLogger(__name__)

# Type alias: (provider_name, provider_instance, provider_config_dict)
_ProviderEntry = tuple[str, BaseStorageProvider, dict[str, Any]]


def _resolve_env_vars(value: str) -> str:
    """Resolve ${VAR} patterns in config strings from environment variables."""
    return os.path.expandvars(value)


class MultiCloudStorageManager:
    """
    Orchestrates multi-cloud storage with automatic provider fallback.

    Tries providers in priority order; on failure retries (per-provider retry config),
    then moves to the next provider. Tracks the fallback_chain on every StorageResult.
    """

    def __init__(
        self,
        providers_config: dict[str, Any],
        providers: list[_ProviderEntry],
    ):
        """
        Initialize the manager.

        Args:
            providers_config: Loaded from providers.yml
            providers: Ordered list of (name, instance, config) tuples (priority ascending)
        """
        # From providers.yml
        self.failover_on: list[str] = providers_config.get("failover_on", [])
        self.max_consecutive_failures: int = providers_config.get(
            "max_consecutive_failures", 3
        )

        self._providers: list[_ProviderEntry] = providers
        self._failure_counts: dict[str, int] = {name: 0 for name, _, _ in providers}

    @classmethod
    def from_configs(
        cls,
        providers_config: dict[str, Any],
        aws_config: dict[str, Any],
        azure_config: dict[str, Any],
        local_config: dict[str, Any],
    ) -> "MultiCloudStorageManager":
        """
        Factory: build the full provider chain from config dicts.

        All values are sourced from the data_acquisition.storage section in config/app.yaml:
        - providers_config  → from storage.providers
        - aws_config        → from storage.aws_s3
        - azure_config      → from storage.azure_blob
        - local_config      → from storage.local_fallback

        Routing keys in providers.yml determine which bucket/container to use.
        """
        routing = providers_config.get("routing", {})

        # ── AWS S3 ──────────────────────────────────────────────────────────────
        aws_routing = routing.get("aws_s3", {})
        bucket_key = aws_routing["bucket_key"]  # from providers.yml, e.g. "clinical-trials-pdfs"
        bucket_cfg = aws_config["buckets"][bucket_key]  # from aws_s3.yml

        s3_flat: dict[str, Any] = {
            "provider": "aws",
            "bucket": bucket_cfg["name"],           # aws_s3.yml → buckets.<key>.name
            "region": aws_config["region"],          # aws_s3.yml → region
            "profile": aws_config.get("profile"),    # aws_s3.yml → profile
            "retry": aws_config.get("retry", {}),    # aws_s3.yml → retry
        }
        # Encryption from bucket config
        if "encryption" in bucket_cfg:
            s3_flat["encryption"] = {"sse_algorithm": bucket_cfg["encryption"]}

        # ── Azure Blob ──────────────────────────────────────────────────────────
        azure_routing = routing.get("azure_blob", {})
        container_key = azure_routing["container_key"]  # from providers.yml
        container_cfg = azure_config["containers"][container_key]  # from azure_blob.yml

        azure_flat: dict[str, Any] = {
            "provider": "azure",
            "container": container_cfg["name"],       # azure_blob.yml → containers.<key>.name
            "connection_string": _resolve_env_vars(   # azure_blob.yml → connection_string (env var)
                azure_config.get("connection_string", "")
            ),
            "account_name": azure_config.get("account"),  # azure_blob.yml → account
            "retry": azure_config.get("retry", {}),       # azure_blob.yml → retry
        }

        # ── Local ───────────────────────────────────────────────────────────────
        # local_config is local_fallback.yml verbatim
        local_flat = dict(local_config)

        # ── Build ordered chain from providers.yml ───────────────────────────────
        name_to_class: dict[str, type] = {
            "aws_s3": S3StorageProvider,
            "azure_blob": AzureBlobStorageProvider,
            "local": LocalStorageProvider,
        }
        name_to_flat_config: dict[str, dict[str, Any]] = {
            "aws_s3": s3_flat,
            "azure_blob": azure_flat,
            "local": local_flat,
        }

        chain_entries = sorted(
            providers_config.get("chain", []), key=lambda e: e.get("priority", 999)
        )

        ordered: list[_ProviderEntry] = []
        for entry in chain_entries:
            name = entry["provider"]
            if name in name_to_class:
                flat_cfg = name_to_flat_config[name]
                instance = name_to_class[name](flat_cfg)
                ordered.append((name, instance, flat_cfg))

        return cls(providers_config, ordered)

    @classmethod
    def local_only(cls, local_config: dict[str, Any]) -> "MultiCloudStorageManager":
        """
        Build a manager with only the local filesystem provider.

        Used when --storage-mode local is set; avoids loading cloud SDKs/configs entirely.
        """
        providers_config: dict[str, Any] = {
            "failover_on": [],
            "max_consecutive_failures": 1,
        }
        instance = LocalStorageProvider(local_config)
        return cls(providers_config, [("local", instance, local_config)])

    # ── Internal helpers ─────────────────────────────────────────────────────────

    async def _store_with_retry(
        self,
        name: str,
        provider: BaseStorageProvider,
        provider_config: dict[str, Any],
        file_path: Path,
        key: str,
        metadata: Optional[dict[str, Any]],
        content_type: str,
    ) -> StorageResult:
        """
        Attempt store with per-provider retry config (from its YAML).
        Returns the last StorageResult after all attempts.
        """
        retry_cfg = provider_config.get("retry", {})
        max_attempts: int = retry_cfg.get("max_attempts", 1)
        backoff_factor: float = retry_cfg.get("backoff_factor", 1.0)
        use_jitter: bool = retry_cfg.get("jitter", False)

        last: Optional[StorageResult] = None

        for attempt in range(max_attempts):
            try:
                result = await provider.store(file_path, key, metadata, content_type)
                if result.success:
                    self._failure_counts[name] = 0
                    return result
                last = result
            except Exception as e:
                last = StorageResult(
                    success=False, provider=name, path=key, error=str(e)
                )

            if attempt < max_attempts - 1:
                delay = backoff_factor ** attempt
                if use_jitter:
                    delay *= 0.5 + random.random()
                logger.warning(
                    f"[{name}] store attempt {attempt + 1}/{max_attempts} failed"
                    f" ({last.error}). Retrying in {delay:.2f}s"
                )
                await asyncio.sleep(delay)

        self._failure_counts[name] = self._failure_counts.get(name, 0) + 1
        return last  # type: ignore[return-value]

    async def _metadata_with_retry(
        self,
        name: str,
        provider: BaseStorageProvider,
        provider_config: dict[str, Any],
        key: str,
        metadata: dict[str, Any],
    ) -> StorageResult:
        """Attempt store_metadata with per-provider retry config."""
        retry_cfg = provider_config.get("retry", {})
        max_attempts: int = retry_cfg.get("max_attempts", 1)
        backoff_factor: float = retry_cfg.get("backoff_factor", 1.0)
        use_jitter: bool = retry_cfg.get("jitter", False)

        last: Optional[StorageResult] = None

        for attempt in range(max_attempts):
            try:
                result = await provider.store_metadata(key, metadata)
                if result.success:
                    self._failure_counts[name] = 0
                    return result
                last = result
            except Exception as e:
                last = StorageResult(
                    success=False, provider=name, path=key, error=str(e)
                )

            if attempt < max_attempts - 1:
                delay = backoff_factor ** attempt
                if use_jitter:
                    delay *= 0.5 + random.random()
                await asyncio.sleep(delay)

        self._failure_counts[name] = self._failure_counts.get(name, 0) + 1
        return last  # type: ignore[return-value]

    def _provider_is_degraded(self, name: str) -> bool:
        """True if provider hit max_consecutive_failures this run."""
        return self._failure_counts.get(name, 0) >= self.max_consecutive_failures

    # ── Public interface ─────────────────────────────────────────────────────────

    async def store(
        self,
        file_path: Path,
        key: str,
        metadata: Optional[dict[str, Any]] = None,
        content_type: str = "application/octet-stream",
    ) -> StorageResult:
        """
        Store a file, falling back through the provider chain on failure.

        fallback_chain on the result lists providers attempted before success.
        """
        fallback_chain: list[str] = []

        for name, provider, provider_config in self._providers:
            if self._provider_is_degraded(name):
                logger.warning(f"Skipping degraded provider [{name}]")
                fallback_chain.append(name)
                continue

            result = await self._store_with_retry(
                name, provider, provider_config, file_path, key, metadata, content_type
            )

            if result.success:
                result.fallback_chain = fallback_chain
                return result

            logger.warning(
                f"[{name}] failed after retries ({result.error}); trying next provider"
            )
            fallback_chain.append(name)

        return StorageResult(
            success=False,
            provider="none",
            path=key,
            error="All providers exhausted",
            fallback_chain=fallback_chain,
        )

    async def retrieve(
        self, key: str, destination_path: Optional[Path] = None
    ) -> Optional[bytes]:
        """Retrieve a file, trying each provider in chain order."""
        for name, provider, _ in self._providers:
            try:
                data = await provider.retrieve(key, destination_path)
                if data is not None:
                    return data
            except Exception as e:
                logger.warning(f"[{name}] retrieve failed: {e}")

        logger.error(f"All providers failed to retrieve: {key}")
        return None

    async def exists(self, key: str) -> bool:
        """Return True if the key exists in any provider."""
        for name, provider, _ in self._providers:
            try:
                if await provider.exists(key):
                    return True
            except Exception as e:
                logger.warning(f"[{name}] exists check failed: {e}")
        return False

    async def delete(self, key: str) -> bool:
        """Delete the key from all providers where it exists."""
        any_success = False
        for name, provider, _ in self._providers:
            try:
                if await provider.exists(key):
                    if await provider.delete(key):
                        logger.info(f"Deleted {key} from [{name}]")
                        any_success = True
            except Exception as e:
                logger.warning(f"[{name}] delete failed: {e}")
        return any_success

    async def store_metadata(self, key: str, metadata: dict[str, Any]) -> StorageResult:
        """Store metadata sidecar, falling back through the provider chain."""
        fallback_chain: list[str] = []

        for name, provider, provider_config in self._providers:
            if self._provider_is_degraded(name):
                fallback_chain.append(name)
                continue

            result = await self._metadata_with_retry(
                name, provider, provider_config, key, metadata
            )

            if result.success:
                result.fallback_chain = fallback_chain
                return result

            logger.warning(f"[{name}] store_metadata failed; trying next provider")
            fallback_chain.append(name)

        return StorageResult(
            success=False,
            provider="none",
            path=key,
            error="All providers exhausted for metadata",
            fallback_chain=fallback_chain,
        )

    async def close(self) -> None:
        """Close all provider clients."""
        for name, provider, _ in self._providers:
            try:
                await provider.close()
                logger.debug(f"Closed [{name}]")
            except Exception as e:
                logger.warning(f"Failed to close [{name}]: {e}")
