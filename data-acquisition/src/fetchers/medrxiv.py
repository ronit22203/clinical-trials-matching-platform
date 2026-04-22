"""
medRxiv PDF fetcher implementation.

Searches medRxiv preprints via the official medRxiv REST API
(https://api.medrxiv.org) using a date-range + keyword filter approach,
and downloads their PDFs directly from www.medrxiv.org.

The DOI is used as the record identifier (nct_id field) throughout, and
pdf_type is always "paper" (medRxiv has one PDF per preprint).

Usage (CLI):
    python medrxiv.py --source medrxiv validate
    python medrxiv.py --source medrxiv search "cancer immunotherapy"
    python medrxiv.py --source medrxiv fetch 10.1101/2021.01.01.425116 paper
"""

import asyncio
import hashlib
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import httpx

try:
    from .base import BaseFetcher, FetchResult, SearchRecord
except ImportError:
    from base import BaseFetcher, FetchResult, SearchRecord

logger = logging.getLogger(__name__)

PDF_TYPE = "paper"
_API_BASE = "https://api.medrxiv.org"


class MedRxivFetcher(BaseFetcher):
    """
    medRxiv implementation of BaseFetcher.

    - search()            — medRxiv REST API date-range scan + keyword filter
    - fetch_pdf()         — downloads PDF from www.medrxiv.org/content/{doi}.full.pdf
    - generate_metadata() — enriches with DOI, authors, abstract, category
    """

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self._validate_config()

        api_cfg = self.api_config
        self.pdf_url_pattern: str = api_cfg["pdf_url_pattern"]
        self.details_endpoint: str = api_cfg["details_endpoint"]
        self.timeout_seconds: int = api_cfg["timeout_seconds"]
        self.max_retries: int = api_cfg["max_retries"]
        self.user_agent: str = api_cfg["user_agent"]
        self.lookback_days: int = api_cfg.get("lookback_days", 30)
        self.page_size: int = api_cfg.get("page_size", 100)

        rate_cfg = self.rate_limit_config
        self.calls_per_minute: int = rate_cfg["calls_per_minute"]

        search_cfg = self.config.get("search", {})
        self.max_results_per_query: int = search_cfg.get("max_results_per_query", 50)

        self._http_client: Optional[httpx.AsyncClient] = None

    def _validate_config(self) -> None:
        required_sections = ["api", "rate_limit", "storage", "metadata"]
        missing = [s for s in required_sections if s not in self.config]
        if missing:
            raise ValueError(f"Missing required config sections: {missing}")

        api_required = ["pdf_url_pattern", "details_endpoint", "timeout_seconds", "max_retries", "user_agent"]
        api_missing = [k for k in api_required if k not in self.api_config]
        if api_missing:
            raise ValueError(f"Missing required api config keys: {api_missing}")

        rate_required = ["calls_per_minute", "concurrency", "burst_size"]
        rate_missing = [k for k in rate_required if k not in self.rate_limit_config]
        if rate_missing:
            raise ValueError(f"Missing required rate_limit config keys: {rate_missing}")

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

    def _matches_query(self, paper: dict[str, Any], keywords: list[str]) -> bool:
        """Return True if any keyword appears in the paper title or abstract."""
        searchable = (
            (paper.get("title") or "") + " " + (paper.get("abstract") or "")
        ).lower()
        return any(kw.lower() in searchable for kw in keywords)

    def _paper_to_record(self, paper: dict[str, Any]) -> SearchRecord:
        """Convert a medRxiv API paper dict to a SearchRecord."""
        doi = paper.get("doi", "")
        authors_raw = paper.get("authors", "")
        # Authors come as a semicolon-separated string: "Smith J; Jones A"
        authors_list = [a.strip() for a in authors_raw.split(";") if a.strip()]
        first_author = authors_list[0] if authors_list else None

        return SearchRecord(
            nct_id=doi,                        # DOI is the primary identifier
            brief_title=paper.get("title"),
            official_title=paper.get("title"),
            lead_sponsor_name=first_author,
            study_type=paper.get("category"),
            last_update_post_date=paper.get("date"),
            raw_data={
                "doi": doi,
                "abstract": paper.get("abstract"),
                "authors": authors_list,
                "medrxiv_category": paper.get("category"),
                "published_date": paper.get("date"),
                "version": paper.get("version"),
                "server": paper.get("server", "medrxiv"),
                "pdf_url": self.pdf_url_pattern.format(doi=doi),
            },
        )

    async def _fetch_page(
        self,
        client: httpx.AsyncClient,
        start_date: str,
        end_date: str,
        cursor: int,
    ) -> dict[str, Any]:
        """Fetch one page from the medRxiv details API."""
        url = (
            f"{_API_BASE}{self.details_endpoint}"
            f"/{start_date}/{end_date}/{cursor}/json"
        )
        for attempt in range(1, self.max_retries + 1):
            try:
                response = await client.get(url)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                if attempt == self.max_retries:
                    raise
                logger.warning(f"HTTP {e.response.status_code} on attempt {attempt}, retrying…")
            except Exception as e:
                if attempt == self.max_retries:
                    raise
                logger.warning(f"Request error on attempt {attempt}: {e}, retrying…")
        return {}

    async def search(self, query: str, max_results: Optional[int] = None) -> list[SearchRecord]:
        """
        Search medRxiv papers posted in the last `lookback_days` that match
        one or more keywords in the query string.

        Args:
            query: Free-text query or comma-separated keywords
            max_results: Cap on results returned (uses config default if None)

        Returns:
            List of SearchRecord objects representing matching preprints
        """
        if max_results is None:
            max_results = self.max_results_per_query

        keywords = [kw.strip() for kw in query.replace(",", " ").split() if kw.strip()]
        end_date = datetime.utcnow().date()
        start_date = end_date - timedelta(days=self.lookback_days)
        start_str, end_str = start_date.isoformat(), end_date.isoformat()

        logger.info(
            f"Searching medRxiv [{start_str} → {end_str}] "
            f"keywords={keywords} (max {max_results})"
        )

        return await self._async_search(keywords, start_str, end_str, max_results)

    async def _async_search(
        self,
        keywords: list[str],
        start_date: str,
        end_date: str,
        max_results: int,
    ) -> list[SearchRecord]:
        records: list[SearchRecord] = []
        cursor = 0
        client = await self._get_client()

        while len(records) < max_results:
            try:
                data = await self._fetch_page(client, start_date, end_date, cursor)
            except Exception as e:
                logger.error(f"Failed to fetch medRxiv page at cursor {cursor}: {e}")
                break

            papers = data.get("collection", [])
            if not papers:
                break  # No more results

            for paper in papers:
                if self._matches_query(paper, keywords):
                    records.append(self._paper_to_record(paper))
                    if len(records) >= max_results:
                        break

            total_available = int(data.get("messages", [{}])[0].get("total", 0))
            cursor += self.page_size
            if cursor >= total_available:
                break

        logger.info(f"Found {len(records)} medRxiv records")
        return records

    async def fetch_pdf(
        self,
        nct_id: str,
        pdf_type: str = PDF_TYPE,
        temp_dir: Optional[Path] = None,
    ) -> Optional[FetchResult]:
        """
        Download a medRxiv PDF by DOI.

        Args:
            nct_id: DOI of the preprint (e.g., "10.1101/2021.01.01.425116")
            pdf_type: Always "paper" for medRxiv
            temp_dir: Directory to write the temporary PDF file

        Returns:
            FetchResult with local path, or a failed FetchResult on error
        """
        pdf_url = self.pdf_url_pattern.format(doi=nct_id)

        if temp_dir is None:
            temp_dir = Path("/tmp/medrxiv")
        temp_dir.mkdir(parents=True, exist_ok=True)

        # Stable filename: MD5 of the DOI (mirrors BioRxivFetcher convention)
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
                logger.warning(f"Unexpected Content-Type for {nct_id}: {content_type}")
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
        Generate metadata for a fetched medRxiv PDF.

        Args:
            record: SearchRecord with raw_data populated from medRxiv API
            pdf_type: Always "paper" for medRxiv
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
        if "abstract" in custom_fields:
            metadata["abstract"] = record.raw_data.get("abstract")
        if "medrxiv_category" in custom_fields:
            metadata["medrxiv_category"] = record.raw_data.get("medrxiv_category")
        if "published_date" in custom_fields:
            metadata["published_date"] = record.raw_data.get("published_date")
        if "version" in custom_fields:
            metadata["version"] = record.raw_data.get("version")

        metadata["source_url"] = self.pdf_url_pattern.format(doi=record.nct_id)
        metadata["source"] = "medrxiv"

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

        Storage key: ``raw/medrxiv/{safe_doi}/paper/{md5}.pdf``

        Args:
            record: SearchRecord (nct_id = DOI)
            storage_manager: MultiCloudStorageManager instance
            temp_dir: Temporary directory for downloads

        Returns:
            Metadata dict on success, None on failure
        """
        fetch_result = await self.fetch_pdf(record.nct_id, PDF_TYPE, temp_dir)

        if not fetch_result or not fetch_result.success:
            return None

        metadata = self.generate_metadata(record, PDF_TYPE, fetch_result)

        prefix = self.storage_config.get("primary", {}).get("prefix", "raw/medrxiv/")
        # DOIs contain slashes; replace with underscores for safe path component
        safe_doi = record.nct_id.replace("/", "_")
        storage_key = f"{prefix}{safe_doi}/{PDF_TYPE}/{fetch_result.pdf_path.name}"

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

    parser = argparse.ArgumentParser(description="medRxiv PDF Fetcher")
    parser.add_argument("--source", default="medrxiv", help="Source name in config/app.yaml")
    parser.add_argument("command", nargs="?", choices=["validate", "search", "fetch"])
    parser.add_argument("args", nargs="*")
    args = parser.parse_args()

    config = load_source_config(args.source)

    if args.command == "validate":
        try:
            MedRxivFetcher(config)
            print("✓ Config is valid")
        except Exception as e:
            print(f"✗ {e}")
            sys.exit(1)

    elif args.command == "search":
        query = args.args[0] if args.args else config.get("search", {}).get("default_query", "clinical trial")
        max_r = int(args.args[1]) if len(args.args) > 1 else None
        fetcher = MedRxivFetcher(config)

        async def _search():
            return await fetcher.search(query, max_r)

        results = asyncio.run(_search())
        for r in results[:10]:
            print(f"  {r.nct_id}: {r.brief_title[:70]}")
        print(f"\nTotal: {len(results)}")

    elif args.command == "fetch":
        if len(args.args) < 1:
            print("Usage: fetch <doi>")
            sys.exit(1)
        doi = args.args[0]

        async def run():
            fetcher = MedRxivFetcher(config)
            try:
                result = await fetcher.fetch_pdf(doi)
                if result and result.success:
                    print(f"✓ {result.pdf_path} ({result.file_size_bytes} bytes)")
                else:
                    print(f"✗ {result.error if result else 'unknown error'}")
            finally:
                await fetcher.close()

        asyncio.run(run())

    else:
        parser.print_help()
