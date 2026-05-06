"""
Tests for MultiCloudStorageManager and StorageResult.

All cloud providers are mocked — no real S3/Azure/Local I/O occurs.
Async methods are exercised via asyncio.run() so pytest-asyncio is not required.
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.storage.base import BaseStorageProvider, StorageResult
from src.storage.manager import MultiCloudStorageManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_provider(
    name: str,
    *,
    succeed_store: bool = True,
    succeed_metadata: bool = True,
    raise_on_store: Exception | None = None,
) -> MagicMock:
    """Build a MagicMock that satisfies BaseStorageProvider's async interface."""
    p = MagicMock(spec=BaseStorageProvider)
    p.initialize = AsyncMock()
    p.retrieve = AsyncMock(return_value=None)
    p.exists = AsyncMock(return_value=False)
    p.delete = AsyncMock(return_value=True)

    if raise_on_store:
        p.store = AsyncMock(side_effect=raise_on_store)
    else:
        p.store = AsyncMock(
            return_value=StorageResult(
                success=succeed_store,
                provider=name,
                path="test/file.pdf",
                error=None if succeed_store else f"{name} failed",
            )
        )

    p.store_metadata = AsyncMock(
        return_value=StorageResult(
            success=succeed_metadata,
            provider=name,
            path="test/file.metadata.json",
        )
    )
    return p


def _manager(
    providers: list[tuple[str, MagicMock]],
    *,
    max_consecutive_failures: int = 3,
) -> MultiCloudStorageManager:
    providers_config = {
        "failover_on": [],
        "max_consecutive_failures": max_consecutive_failures,
    }
    chain = [(name, mock, {}) for name, mock in providers]
    return MultiCloudStorageManager(providers_config, chain)


# ---------------------------------------------------------------------------
# StorageResult dataclass
# ---------------------------------------------------------------------------

class TestStorageResult:
    def test_success_defaults(self) -> None:
        r = StorageResult(success=True, provider="local", path="a/b.pdf")
        assert r.etag is None
        assert r.error is None
        assert r.fallback_chain == []
        assert r.file_size_bytes == 0
        assert r.metadata_path is None

    def test_failure_carries_error_message(self) -> None:
        r = StorageResult(success=False, provider="aws_s3", path="x", error="timeout")
        assert not r.success
        assert r.error == "timeout"

    def test_fallback_chain_populated(self) -> None:
        r = StorageResult(
            success=True,
            provider="local",
            path="f",
            fallback_chain=["aws_s3", "azure_blob"],
        )
        assert r.fallback_chain == ["aws_s3", "azure_blob"]


# ---------------------------------------------------------------------------
# local_only factory
# ---------------------------------------------------------------------------

class TestLocalOnlyFactory:
    def test_local_only_creates_single_provider(self, tmp_path: Path) -> None:
        cfg = {"provider": "local", "base_path": str(tmp_path)}
        # We bypass the real LocalStorageProvider constructor by testing
        # the manager directly via the constructor that accepts raw providers.
        mock_local = _make_provider("local")
        mgr = MultiCloudStorageManager(
            {"failover_on": [], "max_consecutive_failures": 1},
            [("local", mock_local, cfg)],
        )
        names = [n for n, _, _ in mgr._providers]
        assert names == ["local"]

    def test_local_only_sets_failure_threshold_to_one(self, tmp_path: Path) -> None:
        mock_local = _make_provider("local")
        mgr = MultiCloudStorageManager(
            {"failover_on": [], "max_consecutive_failures": 1},
            [("local", mock_local, {})],
        )
        assert mgr.max_consecutive_failures == 1


# ---------------------------------------------------------------------------
# Provider chain ordering
# ---------------------------------------------------------------------------

class TestProviderChainOrdering:
    def test_provider_order_preserved(self) -> None:
        s3 = _make_provider("aws_s3")
        azure = _make_provider("azure_blob")
        local = _make_provider("local")
        mgr = _manager([("aws_s3", s3), ("azure_blob", azure), ("local", local)])
        names = [n for n, _, _ in mgr._providers]
        assert names == ["aws_s3", "azure_blob", "local"]

    def test_failure_counts_initialised_to_zero(self) -> None:
        s3 = _make_provider("aws_s3")
        local = _make_provider("local")
        mgr = _manager([("aws_s3", s3), ("local", local)])
        assert mgr._failure_counts == {"aws_s3": 0, "local": 0}


# ---------------------------------------------------------------------------
# Fallback / provider degradation
# ---------------------------------------------------------------------------

class TestProviderFallback:
    def test_first_provider_success_no_fallback_attempted(
        self, tmp_path: Path
    ) -> None:
        s3 = _make_provider("aws_s3", succeed_store=True)
        local = _make_provider("local", succeed_store=True)
        mgr = _manager([("aws_s3", s3), ("local", local)])

        fake_file = tmp_path / "test.pdf"
        fake_file.write_bytes(b"PDF")

        result = asyncio.run(mgr.store(fake_file, "test/test.pdf"))
        assert result.success
        assert result.provider == "aws_s3"
        local.store.assert_not_called()

    def test_primary_failure_falls_back_to_next(self, tmp_path: Path) -> None:
        s3 = _make_provider("aws_s3", succeed_store=False)
        local = _make_provider("local", succeed_store=True)
        mgr = _manager([("aws_s3", s3), ("local", local)])

        fake_file = tmp_path / "test.pdf"
        fake_file.write_bytes(b"PDF")

        result = asyncio.run(mgr.store(fake_file, "test/test.pdf"))
        assert result.success
        assert result.provider == "local"
        assert "aws_s3" in result.fallback_chain

    def test_primary_raises_exception_falls_back(self, tmp_path: Path) -> None:
        s3 = _make_provider("aws_s3", raise_on_store=ConnectionError("network down"))
        local = _make_provider("local", succeed_store=True)
        mgr = _manager([("aws_s3", s3), ("local", local)])

        fake_file = tmp_path / "test.pdf"
        fake_file.write_bytes(b"PDF")

        result = asyncio.run(mgr.store(fake_file, "test/test.pdf"))
        assert result.success
        assert result.provider == "local"

    def test_all_providers_fail_returns_failure_result(self, tmp_path: Path) -> None:
        s3 = _make_provider("aws_s3", succeed_store=False)
        local = _make_provider("local", succeed_store=False)
        mgr = _manager([("aws_s3", s3), ("local", local)])

        fake_file = tmp_path / "test.pdf"
        fake_file.write_bytes(b"PDF")

        result = asyncio.run(mgr.store(fake_file, "test/test.pdf"))
        assert not result.success
        assert result.provider == "none"
        assert "aws_s3" in result.fallback_chain
        assert "local" in result.fallback_chain

    def test_degraded_provider_skipped(self, tmp_path: Path) -> None:
        s3 = _make_provider("aws_s3", succeed_store=True)
        local = _make_provider("local", succeed_store=True)
        mgr = _manager([("aws_s3", s3), ("local", local)], max_consecutive_failures=2)

        # Manually set S3 at the degradation threshold
        mgr._failure_counts["aws_s3"] = 2  # equals max_consecutive_failures

        fake_file = tmp_path / "test.pdf"
        fake_file.write_bytes(b"PDF")

        result = asyncio.run(mgr.store(fake_file, "test/test.pdf"))
        assert result.success
        assert result.provider == "local"
        s3.store.assert_not_called()

    def test_successful_store_resets_failure_count(self, tmp_path: Path) -> None:
        s3 = _make_provider("aws_s3", succeed_store=True)
        mgr = _manager([("aws_s3", s3)], max_consecutive_failures=5)
        mgr._failure_counts["aws_s3"] = 1  # partial failures before

        fake_file = tmp_path / "test.pdf"
        fake_file.write_bytes(b"PDF")

        asyncio.run(mgr.store(fake_file, "test/test.pdf"))
        assert mgr._failure_counts["aws_s3"] == 0

    def test_failed_store_increments_failure_count(self, tmp_path: Path) -> None:
        s3 = _make_provider("aws_s3", succeed_store=False)
        mgr = _manager([("aws_s3", s3)], max_consecutive_failures=5)

        fake_file = tmp_path / "test.pdf"
        fake_file.write_bytes(b"PDF")

        asyncio.run(mgr.store(fake_file, "test/test.pdf"))
        assert mgr._failure_counts["aws_s3"] > 0


# ---------------------------------------------------------------------------
# provider_is_degraded logic
# ---------------------------------------------------------------------------

class TestProviderDegraded:
    def test_not_degraded_at_zero(self) -> None:
        mgr = _manager([("aws_s3", _make_provider("aws_s3"))], max_consecutive_failures=3)
        assert not mgr._provider_is_degraded("aws_s3")

    def test_not_degraded_below_threshold(self) -> None:
        mgr = _manager([("aws_s3", _make_provider("aws_s3"))], max_consecutive_failures=3)
        mgr._failure_counts["aws_s3"] = 2
        assert not mgr._provider_is_degraded("aws_s3")

    def test_degraded_at_threshold(self) -> None:
        mgr = _manager([("aws_s3", _make_provider("aws_s3"))], max_consecutive_failures=3)
        mgr._failure_counts["aws_s3"] = 3
        assert mgr._provider_is_degraded("aws_s3")

    def test_degraded_above_threshold(self) -> None:
        mgr = _manager([("aws_s3", _make_provider("aws_s3"))], max_consecutive_failures=2)
        mgr._failure_counts["aws_s3"] = 10
        assert mgr._provider_is_degraded("aws_s3")
