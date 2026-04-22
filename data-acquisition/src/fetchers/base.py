"""
Base fetcher abstract class defining the interface for all document fetchers.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class FetchResult:
    """Result of a single fetch operation."""

    nct_id: str
    pdf_type: str  # 'protocol' or 'results'
    pdf_path: Path
    metadata: dict[str, Any] = field(default_factory=dict)
    success: bool = True
    error: Optional[str] = None
    fetched_at: datetime = field(default_factory=datetime.utcnow)
    file_size_bytes: int = 0
    fallback_used: bool = False
    fallback_reason: Optional[str] = None


@dataclass
class SearchRecord:
    """A single record returned from a search operation."""

    nct_id: str
    brief_title: str
    official_title: Optional[str] = None
    overall_status: Optional[str] = None
    lead_sponsor_name: Optional[str] = None
    study_type: Optional[str] = None
    phase: Optional[str] = None
    enrollment_count: Optional[int] = None
    last_update_post_date: Optional[str] = None
    raw_data: dict[str, Any] = field(default_factory=dict)


class BaseFetcher(ABC):
    """
    Abstract base class that defines what every fetcher must implement.

    Provides the interface for:
    - search(): Find records from the source
    - fetch_pdf(): Download PDFs to local storage
    - generate_metadata(): Create metadata sidecars
    - cleanup(): Remove temp files
    """

    def __init__(self, config: dict[str, Any]):
        """
        Initialize the fetcher with configuration.

        Args:
            config: Configuration dictionary loaded from YAML
        """
        self.config = config
        self.name = config.get("name", "base_fetcher")
        self._temp_files: list[Path] = []

    @abstractmethod
    def search(self, query: str, max_results: int = 100) -> list[SearchRecord]:
        """
        Search for records from the source.

        Args:
            query: Search query string
            max_results: Maximum number of results to return

        Returns:
            List of SearchRecord objects
        """
        pass

    @abstractmethod
    def fetch_pdf(
        self, nct_id: str, pdf_type: str = "protocol"
    ) -> Optional[FetchResult]:
        """
        Download a PDF from the source.

        Args:
            nct_id: Clinical trial identifier
            pdf_type: Type of PDF ('protocol' or 'results')

        Returns:
            FetchResult object with PDF path and metadata, or None if failed
        """
        pass

    @abstractmethod
    def generate_metadata(self, record: SearchRecord, pdf_type: str) -> dict[str, Any]:
        """
        Generate metadata for a fetched PDF.

        Args:
            record: The search record associated with the PDF
            pdf_type: Type of PDF ('protocol' or 'results')

        Returns:
            Dictionary of metadata fields
        """
        pass

    def cleanup(self) -> None:
        """
        Remove temporary files created during fetch operations.

        Should be called after successful upload to permanent storage.
        """
        for temp_file in self._temp_files:
            try:
                if temp_file.exists():
                    temp_file.unlink()
                    logger.debug(f"Cleaned up temp file: {temp_file}")
            except Exception as e:
                logger.warning(f"Failed to clean up {temp_file}: {e}")
        self._temp_files.clear()

    def _track_temp_file(self, path: Path) -> None:
        """Track a temporary file for later cleanup."""
        self._temp_files.append(path)

    def _format_url(self, pattern: str, nct_id: str) -> str:
        """
        Format a URL pattern with an NCT ID.

        Args:
            pattern: URL pattern with placeholders
            nct_id: Clinical trial ID (e.g., 'NCT1234567')

        Returns:
            Formatted URL string
        """
        # Extract last two digits for URL path structure
        last_two = nct_id[-2:] if len(nct_id) >= 2 else nct_id
        return pattern.format(nct_id=nct_id, last_two=last_two)

    @property
    def rate_limit_config(self) -> dict[str, Any]:
        """Get rate limit configuration from config."""
        return self.config.get("rate_limit", {})

    @property
    def api_config(self) -> dict[str, Any]:
        """Get API configuration from config."""
        return self.config.get("api", {})

    @property
    def storage_config(self) -> dict[str, Any]:
        """Get storage configuration from config."""
        return self.config.get("storage", {})
