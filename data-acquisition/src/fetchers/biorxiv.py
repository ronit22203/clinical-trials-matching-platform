"""
bioRxiv PDF fetcher implementation.

Searches bioRxiv preprints via the arXiv API (q-bio category / 10.1101 DOIs)
and downloads their PDFs into the multi-cloud storage pipeline.

The arXiv ID is used as the record identifier (nct_id field) throughout, and
pdf_type is always "paper" (bioRxiv has one PDF per preprint).

Usage (CLI):
    python biorxiv.py --source biorxiv validate
    python biorxiv.py --source biorxiv search "cancer immunotherapy"
    python biorxiv.py --source biorxiv fetch 2301.12345v1 paper
"""

import asyncio
import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import httpx

try:
    import arxiv
except ImportError:
    arxiv = None  # type: ignore[assignment]

try:
    from .base import BaseFetcher, FetchResult, SearchRecord
except ImportError:
    from base import BaseFetcher, FetchResult, SearchRecord

logger = logging.getLogger(__name__)

PDF_TYPE = "paper"


class BioRxivFetcher(BaseFetcher):
    """
    bioRxiv implementation of BaseFetcher.

    - search()     — arXiv API (arxiv library), filters for bioRxiv papers
    - fetch_pdf()  — downloads PDF directly from arxiv.org/pdf/<id>
    - generate_metadata() — enriches with DOI, authors, summary
    """

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self._validate_config()

        api_cfg = self.api_config
        self.pdf_url_pattern: str = api_cfg["pdf_url_pattern"]
        self.timeout_seconds: int = api_cfg["timeout_seconds"]
        self.max_retries: int = api_cfg["max_retries"]
        self.user_agent: str = api_cfg["user_agent"]

        rate_cfg = self.rate_limit_config
        self.calls_per_minute: int = rate_cfg["calls_per_minute"]

        search_cfg = self.config.get("search", {})
        self.biorxiv_filter: str = search_cfg.get(
            "biorxiv_filter", "(all:bioRxiv OR all:q-bio)"
        )
        self.max_results_per_query: int = search_cfg.get("max_results_per_query", 50)

        self._http_client: Optional[httpx.AsyncClient] = None

    def _validate_config(self) -> None:
        required_sections = ["api", "rate_limit", "storage", "metadata"]
        missing = [s for s in required_sections if s not in self.config]
        if missing:
            raise ValueError(f"Missing required config sections: {missing}")

        api_required = ["pdf_url_pattern", "timeout_seconds", "max_retries", "user_agent"]
        api_missing = [k for k in api_required if k not in self.api_config]
        if api_missing:
            raise ValueError(f"Missing required api config keys: {api_missing}")

        rate_required = ["calls_per_minute", "concurrency", "burst_size"]
        rate_missing = [k for k in rate_required if k not in self.rate_limit_config]
        if rate_missing:
            raise ValueError(f"Missing required rate_limit config keys: {rate_missing}")

        if arxiv is None:
            raise ImportError("arxiv package is required: pip install arxiv")

        logger.info(f"Config validated for {self.name}")

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_seconds),
                headers={"User-Agent": self.user_agent},
                follow_redirects=True,
            )
        return self._http_client

    async def close(self) -> None:
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None

    def _build_arxiv_query(self, query: str) -> str:
        """Combine the user query with the bioRxiv filter."""
        terms = " AND ".join(f"all:{kw.strip()}" for kw in query.split(",") if kw.strip())
        return f"({terms}) AND {self.biorxiv_filter}"

    def _is_biorxiv(self, result: Any) -> bool:
        """True if the arXiv result is a bioRxiv preprint."""
        return (result.doi and result.doi.startswith("10.1101")) or any(
            "q-bio" in str(cat) for cat in result.categories
        )

    def _result_to_record(self, result: Any) -> SearchRecord:
        """Convert an arxiv.Result to a SearchRecord."""
        return SearchRecord(
            nct_id=result.get_short_id(),          # used as primary identifier
            brief_title=result.title,
            official_title=result.title,
            lead_sponsor_name=(
                result.authors[0].name if result.authors else None
            ),
            study_type=result.primary_category,
            last_update_post_date=(
                result.published.isoformat() if result.published else None
            ),
            raw_data={
                "doi": result.doi,
                "summary": result.summary,
                "authors": [a.name for a in result.authors],
                "pdf_url": result.pdf_url,
                "categories": [str(c) for c in result.categories],
                "arxiv_id": result.get_short_id(),
            },
        )

    def search(self, query: str, max_results: Optional[int] = None) -> list[SearchRecord]:
        """
        Search bioRxiv papers via the arXiv API.

        Args:
            query: Free-text query or comma-separated keywords
            max_results: Cap on results returned (uses config default if None)

        Returns:
            List of SearchRecord objects representing matching preprints
        """
        if max_results is None:
            max_results = self.max_results_per_query

        full_query = self._build_arxiv_query(query)
        logger.info(f"Searching arXiv: {full_query} (max {max_results})")

        client = arxiv.Client()
        search = arxiv.Search(
            query=full_query,
            # Fetch 2× so bioRxiv filtering still hits the target count
            max_results=max_results * 2,
            sort_by=arxiv.SortCriterion.SubmittedDate,
        )

        records: list[SearchRecord] = []
        try:
            for result in client.results(search):
                if self._is_biorxiv(result):
                    records.append(self._result_to_record(result))
                    if len(records) >= max_results:
                        break
        except Exception as e:
            logger.error(f"Error searching arXiv: {e}")

        logger.info(f"Found {len(records)} bioRxiv records")
        return records

    async def fetch_pdf(
        self,
        nct_id: str,
        pdf_type: str = PDF_TYPE,
        temp_dir: Optional[Path] = None,
    ) -> Optional[FetchResult]:
        """
        Download a bioRxiv PDF by arXiv ID.

        Args:
            nct_id: arXiv short ID (e.g., "2301.12345v1")
            pdf_type: Always "paper" for bioRxiv
            temp_dir: Directory to write the temporary PDF file

        Returns:
            FetchResult with local path, or a failed FetchResult on error
        """
        pdf_url = self.pdf_url_pattern.format(arxiv_id=nct_id)

        if temp_dir is None:
            temp_dir = Path("/tmp/biorxiv")
        temp_dir.mkdir(parents=True, exist_ok=True)

        # Stable filename: MD5 of the arXiv ID (mirrors existing downloader)
        filename = hashlib.md5(nct_id.encode()).hexdigest() + ".pdf"
        temp_file = temp_dir / filename

        logger.info(f"Fetching PDF for {nct_id} from {pdf_url}")

        try:
            client = await self._get_client()
            response = await client.get(pdf_url)

            if response.status_code == 404:
                logger.warning(f"PDF not found for {nct_id} (404)")
                return FetchResult(
                    nct_id=nct_id,
                    pdf_type=pdf_type,
                    pdf_path=temp_file,
                    success=False,
                    error="PDF not available (404)",
                )

            response.raise_for_status()

            content_type = response.headers.get("Content-Type", "")
            if "pdf" not in content_type.lower():
                logger.warning(
                    f"Unexpected Content-Type for {nct_id}: {content_type}"
                )
                return FetchResult(
                    nct_id=nct_id,
                    pdf_type=pdf_type,
                    pdf_path=temp_file,
                    success=False,
                    error=f"Unexpected Content-Type: {content_type}",
                )

            temp_file.write_bytes(response.content)
            file_size = temp_file.stat().st_size
            self._track_temp_file(temp_file)

            logger.info(f"Downloaded {nct_id} → {temp_file.name} ({file_size} bytes)")

            return FetchResult(
                nct_id=nct_id,
                pdf_type=pdf_type,
                pdf_path=temp_file,
                success=True,
                file_size_bytes=file_size,
            )

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error fetching {nct_id}: {e}")
            return FetchResult(
                nct_id=nct_id, pdf_type=pdf_type, pdf_path=temp_file,
                success=False, error=str(e),
            )
        except Exception as e:
            logger.error(f"Unexpected error fetching {nct_id}: {e}")
            return FetchResult(
                nct_id=nct_id, pdf_type=pdf_type, pdf_path=temp_file,
                success=False, error=str(e),
            )

    def generate_metadata(
        self,
        record: SearchRecord,
        pdf_type: str,
        fetch_result: Optional[FetchResult] = None,
    ) -> dict[str, Any]:
        """
        Generate metadata for a fetched bioRxiv PDF.

        Args:
            record: SearchRecord with raw_data populated from arXiv API
            pdf_type: Always "paper" for bioRxiv
            fetch_result: Optional FetchResult to include file-level metadata

        Returns:
            Metadata dictionary ready for storage sidecar
        """
        metadata_cfg = self.config.get("metadata", {})
        include_fields = metadata_cfg.get("include_fields", [])
        custom_fields = metadata_cfg.get("custom_fields", [])

        metadata: dict[str, Any] = {}

        for field in include_fields:
            value = getattr(record, field, None)
            if value is not None:
                metadata[field] = value

        if "fetched_at" in custom_fields:
            metadata["fetched_at"] = datetime.utcnow().isoformat()
        if "source_version" in custom_fields:
            metadata["source_version"] = metadata_cfg.get("version", "1.0")
        if "pdf_type" in custom_fields:
            metadata["pdf_type"] = pdf_type
        if "doi" in custom_fields:
            metadata["doi"] = record.raw_data.get("doi")
        if "authors" in custom_fields:
            metadata["authors"] = record.raw_data.get("authors", [])
        if "summary" in custom_fields:
            metadata["summary"] = record.raw_data.get("summary")
        if "arxiv_id" in custom_fields:
            metadata["arxiv_id"] = record.raw_data.get("arxiv_id")

        metadata["source_url"] = self.pdf_url_pattern.format(arxiv_id=record.nct_id)
        metadata["source"] = "biorxiv"

        if fetch_result is not None:
            metadata["file_size_bytes"] = fetch_result.file_size_bytes
            metadata["fallback_used"] = fetch_result.fallback_used
            if fetch_result.fallback_reason:
                metadata["fallback_reason"] = fetch_result.fallback_reason

        return metadata

    async def fetch_and_store(
        self,
        record: SearchRecord,
        storage_manager: Any,
        temp_dir: Optional[Path] = None,
    ) -> Optional[dict[str, Any]]:
        """
        Fetch a PDF and store it via the multi-cloud storage manager.

        Storage key: ``raw/biorxiv/{arxiv_id}/paper/{md5}.pdf``

        Args:
            record: SearchRecord (nct_id = arXiv short ID)
            storage_manager: MultiCloudStorageManager instance
            temp_dir: Temporary directory for downloads

        Returns:
            Metadata dict on success, None on failure
        """
        fetch_result = await self.fetch_pdf(record.nct_id, PDF_TYPE, temp_dir)

        if not fetch_result or not fetch_result.success:
            return None

        metadata = self.generate_metadata(record, PDF_TYPE, fetch_result)

        prefix = self.storage_config.get("primary", {}).get("prefix", "raw/biorxiv/")
        storage_key = f"{prefix}{record.nct_id}/{PDF_TYPE}/{fetch_result.pdf_path.name}"

        try:
            storage_result = await storage_manager.store(
                file_path=fetch_result.pdf_path,
                key=storage_key,
                metadata=metadata,
                content_type="application/pdf",
            )

            if storage_result.success:
                logger.info(
                    f"Stored {storage_key} via {storage_result.provider}"
                    + (
                        f" (fallback from {storage_result.fallback_chain})"
                        if storage_result.fallback_chain
                        else ""
                    )
                )
                metadata["storage_provider"] = storage_result.provider
                metadata["storage_path"] = storage_result.path
                metadata["storage_etag"] = storage_result.etag
                return metadata
            else:
                logger.error(f"Failed to store {storage_key}: {storage_result.error}")
                return None

        except Exception as e:
            logger.error(f"Error storing {storage_key}: {e}")
            return None


if __name__ == "__main__":
    import argparse
    import sys
    try:
        from src.config_loader import load_source_config
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from src.config_loader import load_source_config

    parser = argparse.ArgumentParser(description="bioRxiv PDF Fetcher")
    parser.add_argument("--source", default="biorxiv", help="Source name in config/app.yaml")
    parser.add_argument("command", nargs="?", choices=["validate", "search", "fetch"])
    parser.add_argument("args", nargs="*")
    args = parser.parse_args()

    config = load_source_config(args.source)

    if args.command == "validate":
        try:
            BioRxivFetcher(config)
            print("✓ Config is valid")
        except Exception as e:
            print(f"✗ {e}")
            sys.exit(1)

    elif args.command == "search":
        query = args.args[0] if args.args else config.get("search", {}).get("default_query", "cancer")
        max_r = int(args.args[1]) if len(args.args) > 1 else None
        fetcher = BioRxivFetcher(config)
        results = fetcher.search(query, max_r)
        for r in results[:10]:
            print(f"  {r.nct_id}: {r.brief_title[:70]}")
        print(f"\nTotal: {len(results)}")

    elif args.command == "fetch":
        if len(args.args) < 1:
            print("Usage: fetch <arxiv_id>")
            sys.exit(1)
        arxiv_id = args.args[0]

        async def run():
            fetcher = BioRxivFetcher(config)
            try:
                result = await fetcher.fetch_pdf(arxiv_id)
                if result and result.success:
                    print(f"✓ {result.pdf_path} ({result.file_size_bytes} bytes)")
                else:
                    print(f"✗ {result.error if result else 'unknown error'}")
            finally:
                await fetcher.close()

        asyncio.run(run())

    else:
        parser.print_help()
