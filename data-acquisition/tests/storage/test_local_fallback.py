"""
Integration tests for local fallback storage.

Tests the catastrophic fallback tier using local filesystem.
"""

import os
import json
import shutil
from pathlib import Path

import pytest


pytestmark = pytest.mark.local


class TestLocalFallbackConfig:
    """Test local fallback configuration."""

    def test_local_config(self, local_fallback_config):
        """Verify local fallback configuration."""
        assert local_fallback_config["provider"] == "local"
        assert local_fallback_config["enabled"] is True
        assert local_fallback_config["priority"] == 1
        assert local_fallback_config["retention_days"] == 365

    def test_base_directory_config(self, local_fallback_config):
        """Verify base directory configuration."""
        paths = local_fallback_config["paths"]
        assert "base_dir" in paths
        assert paths["base_dir"] == "../data/pdfs"

    def test_path_templates(self, local_fallback_config):
        """Verify path templates are properly configured."""
        paths = local_fallback_config["paths"]
        assert "{base_dir}" in paths["raw"]
        assert "{base_dir}" in paths["metadata"]
        assert "{base_dir}" in paths["manifests"]


class TestLocalPathTemplates:
    """Test local path template rendering."""

    def test_raw_path_template(self, local_fallback_config, sample_metadata):
        """Test raw PDF path template."""
        paths = local_fallback_config["paths"]
        template = paths["raw"]
        base_dir = "/data/graphrag/fallback"

        rendered = template.format(
            base_dir=base_dir,
            source="clinical_trials",
            year="2026",
            month="03",
            day="03",
            nct_id=sample_metadata["nct_id"],
        )

        expected = "/data/graphrag/fallback/raw/clinical_trials/2026/03/03/NCT01234567/"
        assert rendered == expected

    def test_metadata_path_template(self, local_fallback_config, sample_metadata):
        """Test metadata path template."""
        paths = local_fallback_config["paths"]
        template = paths["metadata"]
        base_dir = "/data/graphrag/fallback"

        rendered = template.format(
            base_dir=base_dir,
            source="clinical_trials",
            year="2026",
            month="03",
            day="03",
        )

        expected = "/data/graphrag/fallback/metadata/clinical_trials/2026/03/03/"
        assert rendered == expected

    def test_manifests_path_template(self, local_fallback_config):
        """Test manifests path template."""
        paths = local_fallback_config["paths"]
        template = paths["manifests"]
        base_dir = "/data/graphrag/fallback"

        rendered = template.format(
            base_dir=base_dir,
            source="clinical_trials",
        )

        expected = "/data/graphrag/fallback/manifests/clinical_trials/"
        assert rendered == expected


class TestLocalStorageOperations:
    """Test local storage operations."""

    @pytest.fixture
    def local_storage_dir(self, temp_dir: Path) -> Path:
        """Create local storage directory structure."""
        base_dir = temp_dir / "fallback"
        (base_dir / "raw" / "clinical_trials").mkdir(parents=True, exist_ok=True)
        (base_dir / "metadata" / "clinical_trials").mkdir(parents=True, exist_ok=True)
        (base_dir / "manifests" / "clinical_trials").mkdir(parents=True, exist_ok=True)
        return base_dir

    def test_upload_pdf_file(self, local_storage_dir: Path, sample_pdf_content, sample_metadata):
        """Test uploading a PDF file to local storage."""
        pdf_path = local_storage_dir / "raw" / "clinical_trials" / f"{sample_metadata['nct_id']}_protocol.pdf"

        pdf_path.write_bytes(sample_pdf_content)
        assert pdf_path.exists()
        assert pdf_path.read_bytes() == sample_pdf_content

    def test_upload_metadata_json(self, local_storage_dir: Path, sample_metadata):
        """Test uploading metadata JSON to local storage."""
        metadata_path = local_storage_dir / "metadata" / "clinical_trials" / f"{sample_metadata['nct_id']}.json"

        metadata_path.write_text(json.dumps(sample_metadata, indent=2))
        assert metadata_path.exists()

        loaded = json.loads(metadata_path.read_text())
        assert loaded["nct_id"] == sample_metadata["nct_id"]

    def test_create_manifest(self, local_storage_dir: Path):
        """Test creating a manifest file."""
        manifest = {
            "run_id": "run-12345",
            "source": "clinical_trials",
            "created_at": "2026-03-03T00:00:00Z",
            "files": [
                {"nct_id": "NCT01234567", "type": "protocol", "status": "success"},
                {"nct_id": "NCT01234568", "type": "results", "status": "success"},
            ],
            "total_files": 2,
        }

        manifest_path = local_storage_dir / "manifests" / "clinical_trials" / "run-12345.json"
        manifest_path.write_text(json.dumps(manifest, indent=2))
        assert manifest_path.exists()

    def test_list_files_in_directory(self, local_storage_dir: Path, sample_pdf_content):
        """Test listing files in a directory."""
        # Create test files
        for i in range(3):
            pdf_path = local_storage_dir / "raw" / "clinical_trials" / f"test_{i}.pdf"
            pdf_path.write_bytes(sample_pdf_content)

        # List PDF files
        pdf_files = list((local_storage_dir / "raw" / "clinical_trials").glob("*.pdf"))
        assert len(pdf_files) == 3

    def test_cleanup_old_files(self, local_storage_dir: Path, sample_pdf_content):
        """Test cleaning up files older than retention period."""
        import time

        # Create a test file
        pdf_path = local_storage_dir / "raw" / "clinical_trials" / "old_file.pdf"
        pdf_path.write_bytes(sample_pdf_content)

        # Set modification time to 10 days ago
        old_time = time.time() - (10 * 24 * 60 * 60)
        os.utime(pdf_path, (old_time, old_time))

        # Find files older than 7 days
        retention_days = 7
        cutoff_time = time.time() - (retention_days * 24 * 60 * 60)

        files_to_delete = []
        for pdf_file in (local_storage_dir / "raw" / "clinical_trials").glob("*.pdf"):
            if pdf_file.stat().st_mtime < cutoff_time:
                files_to_delete.append(pdf_file)

        assert len(files_to_delete) == 1
        assert files_to_delete[0].name == "old_file.pdf"


class TestLocalTriggers:
    """Test local fallback trigger configuration."""

    def test_trigger_conditions(self, local_fallback_config):
        """Verify trigger conditions."""
        triggers = local_fallback_config["triggers"]
        assert "local_mode_default" in triggers


class TestLocalCleanup:
    """Test local cleanup configuration."""

    def test_cleanup_schedule(self, local_fallback_config):
        """Verify cleanup configuration."""
        cleanup = local_fallback_config["cleanup"]
        assert cleanup["enabled"] is False
        assert cleanup["min_free_space_gb"] == 10


class TestLocalMetrics:
    """Test local metrics configuration."""

    def test_metrics_tracking(self, local_fallback_config):
        """Verify metrics tracking configuration."""
        metrics = local_fallback_config["metrics"]
        assert metrics["track_disk_usage"] is True
        assert metrics["track_file_count"] is True
        assert metrics["alert_at_percent"] == 90


class TestLocalDiskSpace:
    """Test local disk space management."""

    def test_check_disk_space(self, temp_dir: Path):
        """Test checking available disk space."""

        # Get disk usage
        usage = shutil.disk_usage(temp_dir)

        assert usage.total > 0
        assert usage.used >= 0
        assert usage.free >= 0

    def test_alert_on_low_disk_space(self, temp_dir: Path):
        """Test disk space alert threshold."""

        usage = shutil.disk_usage(temp_dir)
        percent_used = (usage.used / usage.total) * 100

        # Alert threshold is 90%
        alert_threshold = 90

        # This should not trigger alert in normal conditions
        should_alert = percent_used >= alert_threshold
        assert isinstance(should_alert, bool)
