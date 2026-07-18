"""
ClinicalTrials.gov PDF fetcher implementation.

Fetches protocol and results PDFs from ClinicalTrials.gov with:
- API-based search
- Rate limiting compliance
- Multi-cloud storage fallback
- Comprehensive metadata generation
"""

import asyncio
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

try:
    from .base import BaseFetcher, FetchResult, SearchRecord
except ImportError:
    from base import BaseFetcher, FetchResult, SearchRecord

logger = logging.getLogger(__name__)


class ClinicalTrialsFetcher(BaseFetcher):
    """
    ClinicalTrials.gov implementation.

    Implements search() using their API
    Implements fetch_pdf() using their PDF patterns
    Handles rate limiting
    Returns PDFs + metadata
    """

    def __init__(self, config: dict[str, Any]):
        """
        Initialize fetcher with config - NOTHING HARDCODED.

        All values MUST come from config or the fetcher will fail validation.
        """
        super().__init__(config)
        self._client: Optional[httpx.AsyncClient] = None
        self._last_call_time: float = 0
        self._calls_this_minute: int = 0
        self._minute_start: float = time.time()

        # Validate required config sections exist
        self._validate_config()

        # Rate limit configuration - ALL from config, no defaults
        rate_config = self.rate_limit_config
        self.calls_per_minute = rate_config["calls_per_minute"]
        self.concurrency = rate_config["concurrency"]
        self.burst_size = rate_config["burst_size"]

        # API configuration - ALL from config, no defaults
        api_config = self.api_config
        self.base_url = api_config["base_url"]
        self.search_endpoint = api_config["search_endpoint"]
        self.timeout_seconds = api_config["timeout_seconds"]
        self.max_retries = api_config["max_retries"]
        self.user_agent = api_config["user_agent"]

        # PDF patterns - ALL from config
        self.pdf_patterns = api_config["pdf_patterns"]

        # Search configuration
        search_config = self.config.get("search", {})
        self.default_query = search_config.get("default_query")
        self.max_studies_per_query = search_config.get("max_studies_per_query")
        self.max_pdfs_per_run = search_config.get("max_pdfs_per_run")
        self.search_fields = search_config.get("fields", [])

    def _validate_config(self) -> None:
        """
        Validate that all required config sections are present.

        Raises:
            ValueError: If required config is missing
        """
        required_sections = ["api", "rate_limit", "storage", "metadata"]
        missing = [s for s in required_sections if s not in self.config]
        if missing:
            raise ValueError(
                f"Missing required config sections: {missing}. "
                "ALL configuration must come from YAML, nothing is hardcoded."
            )

        # Validate API config
        api_required = ["base_url", "search_endpoint", "pdf_patterns", "timeout_seconds", "max_retries", "user_agent"]
        api_missing = [k for k in api_required if k not in self.api_config]
        if api_missing:
            raise ValueError(f"Missing required API config: {api_missing}")

        # Validate rate limit config
        rate_required = ["calls_per_minute", "concurrency", "burst_size"]
        rate_missing = [k for k in rate_required if k not in self.rate_limit_config]
        if rate_missing:
            raise ValueError(f"Missing required rate_limit config: {rate_missing}")

        logger.info(f"Config validated for {self.name}")

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client with proper configuration."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_seconds),
                headers={"User-Agent": self.user_agent},
                follow_redirects=True,
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _enforce_rate_limit(self) -> None:
        """Enforce rate limiting to be a good API citizen."""
        current_time = time.time()

        # Reset counter if we're in a new minute
        if current_time - self._minute_start >= 60:
            self._calls_this_minute = 0
            self._minute_start = current_time

        # Check if we've hit the limit
        if self._calls_this_minute >= self.calls_per_minute:
            sleep_time = 60 - (current_time - self._minute_start)
            if sleep_time > 0:
                logger.debug(f"Rate limit reached, sleeping for {sleep_time:.2f}s")
                await asyncio.sleep(sleep_time)
                self._calls_this_minute = 0
                self._minute_start = time.time()

        # Add small delay between calls to smooth traffic
        elapsed = current_time - self._last_call_time
        min_interval = 60.0 / self.calls_per_minute
        if elapsed < min_interval:
            await asyncio.sleep(min_interval - elapsed)

        self._calls_this_minute += 1
        self._last_call_time = time.time()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(httpx.HTTPError),
    )
    async def search(
        self, query: str, max_results: Optional[int] = None
    ) -> list[SearchRecord]:
        """
        Search for clinical trials using the ClinicalTrials.gov API.

        Args:
            query: Search query string
            max_results: Maximum number of results (from config if not provided)

        Returns:
            List of SearchRecord objects
        """
        # Use config value if max_results not provided
        if max_results is None:
            max_results = self.max_studies_per_query

        await self._enforce_rate_limit()

        client = await self._get_client()
        url = f"{self.base_url}{self.search_endpoint}"

        # Build query parameters - ALL from config
        params = {
            "query.term": query,
            "pageSize": max_results,
            "countTotal": "true",
        }

        # Note: ClinicalTrials.gov v2 API does not support per-field filtering via
        # a 'fields' query param in the format we have in config. The config's
        # search.fields list controls which fields are extracted in generate_metadata().

        logger.info(f"Searching ClinicalTrials.gov: {query} (max {max_results})")

        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

            studies = data.get("studies", [])
            records = []

            for study in studies:
                protocol = study.get("protocolSection", {})
                record = self._parse_study(protocol)
                if record:
                    records.append(record)

            logger.info(f"Found {len(records)} studies")
            return records

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error during search: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during search: {e}")
            raise

    def _parse_study(self, protocol: dict[str, Any]) -> Optional[SearchRecord]:
        """Parse a study protocol section into a SearchRecord."""
        try:
            id_module = protocol.get("identificationModule", {})
            nct_id = id_module.get("nctId")
            if not nct_id:
                return None

            status_module = protocol.get("statusModule", {})
            # v2 API: sponsorCollaboratorsModule (not sponsorModule)
            sponsor_module = protocol.get("sponsorCollaboratorsModule", {})
            design_module = protocol.get("designModule", {})
            # v2 API: enrollmentInfo is nested inside designModule
            enrollment_info = design_module.get("enrollmentInfo", {})

            return SearchRecord(
                nct_id=nct_id,
                brief_title=id_module.get("briefTitle", ""),
                official_title=id_module.get("officialTitle"),
                overall_status=status_module.get("overallStatus"),
                lead_sponsor_name=sponsor_module.get("leadSponsor", {}).get("name"),
                study_type=design_module.get("studyType"),
                phase=(design_module.get("phases") or ["Unknown"])[0],
                enrollment_count=enrollment_info.get("count"),
                last_update_post_date=status_module.get(
                    "lastUpdatePostDateStruct", {}
                ).get("date"),
                raw_data=protocol,
            )
        except Exception as e:
            logger.warning(f"Failed to parse study: {e}")
            return None

    async def fetch_pdf(
        self, nct_id: str, pdf_type: str = "protocol", temp_dir: Optional[Path] = None
    ) -> Optional[FetchResult]:
        """
        Download a PDF from ClinicalTrials.gov.

        Args:
            nct_id: Clinical trial identifier (e.g., 'NCT1234567')
            pdf_type: Type of PDF ('protocol' or 'results')
            temp_dir: Directory to store temporary files

        Returns:
            FetchResult object with PDF path and metadata, or None if failed
        """
        if pdf_type not in ["protocol", "results"]:
            logger.error(f"Invalid pdf_type: {pdf_type}")
            return None

        # Build PDF URL
        pattern_key = pdf_type
        pattern = self.pdf_patterns.get(pattern_key)

        if not pattern:
            logger.error(f"No PDF pattern found for {pdf_type}")
            return None

        pdf_url = self._format_url(pattern, nct_id)

        # Create temp directory if not provided
        if temp_dir is None:
            temp_dir = Path("/tmp/clinical_trials")
            temp_dir.mkdir(parents=True, exist_ok=True)

        temp_file = temp_dir / f"{nct_id}_{pdf_type}.pdf"

        logger.info(f"Fetching {pdf_type} PDF for {nct_id} from {pdf_url}")

        try:
            await self._enforce_rate_limit()
            client = await self._get_client()

            response = await client.get(pdf_url)

            # Check if PDF exists (404 means no PDF available)
            if response.status_code == 404:
                logger.warning(f"No {pdf_type} PDF available for {nct_id}")
                return FetchResult(
                    nct_id=nct_id,
                    pdf_type=pdf_type,
                    pdf_path=temp_file,
                    success=False,
                    error="PDF not available (404)",
                )

            response.raise_for_status()

            # Write PDF to temp file
            temp_file.write_bytes(response.content)
            file_size = temp_file.stat().st_size

            self._track_temp_file(temp_file)

            logger.info(
                f"Downloaded {pdf_type} PDF for {nct_id} ({file_size} bytes)"
            )

            return FetchResult(
                nct_id=nct_id,
                pdf_type=pdf_type,
                pdf_path=temp_file,
                success=True,
                file_size_bytes=file_size,
            )

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error fetching PDF for {nct_id}: {e}")
            return FetchResult(
                nct_id=nct_id,
                pdf_type=pdf_type,
                pdf_path=temp_file,
                success=False,
                error=str(e),
            )
        except Exception as e:
            logger.error(f"Unexpected error fetching PDF for {nct_id}: {e}")
            return FetchResult(
                nct_id=nct_id,
                pdf_type=pdf_type,
                pdf_path=temp_file,
                success=False,
                error=str(e),
            )

    def generate_metadata(
        self, record: SearchRecord, pdf_type: str, fetch_result: FetchResult
    ) -> dict[str, Any]:
        """
        Generate metadata for a fetched PDF.

        Args:
            record: The search record associated with the PDF
            pdf_type: Type of PDF ('protocol' or 'results')
            fetch_result: The result of the fetch operation

        Returns:
            Dictionary of metadata fields
        """
        metadata_config = self.config.get("metadata", {})
        include_fields = metadata_config.get("include_fields", [])

        # Build base metadata from configured fields
        metadata = {}

        # Add standard fields
        for field in include_fields:
            value = getattr(record, field, None)
            if value is not None:
                metadata[field] = value

        # Add custom fields
        custom_fields = metadata_config.get("custom_fields", [])
        if "fetched_at" in custom_fields:
            metadata["fetched_at"] = datetime.utcnow().isoformat()
        if "source_version" in custom_fields:
            metadata["source_version"] = metadata_config.get("version", "1.0")
        if "pdf_type" in custom_fields:
            metadata["pdf_type"] = pdf_type
        if "processing_tier" in custom_fields:
            metadata["processing_tier"] = "primary"

        # Add fetch-specific metadata
        metadata["file_size_bytes"] = fetch_result.file_size_bytes
        metadata["fallback_used"] = fetch_result.fallback_used
        if fetch_result.fallback_reason:
            metadata["fallback_reason"] = fetch_result.fallback_reason

        # Add source URL
        pattern = self.pdf_patterns.get(pdf_type, "")
        metadata["source_url"] = self._format_url(pattern, record.nct_id)

        return metadata

    async def fetch_and_store(
        self,
        record: SearchRecord,
        pdf_type: str,
        storage_manager: Any,
        temp_dir: Optional[Path] = None,
    ) -> Optional[dict[str, Any]]:
        """
        Fetch a PDF and store it with metadata.

        Args:
            record: Search record for the trial
            pdf_type: Type of PDF to fetch
            storage_manager: Multi-cloud storage manager instance
            temp_dir: Temporary directory for downloads

        Returns:
            Metadata dict if successful, None if failed
        """
        # Fetch the PDF
        fetch_result = await self.fetch_pdf(record.nct_id, pdf_type, temp_dir)

        if not fetch_result or not fetch_result.success:
            return None

        # Generate metadata
        metadata = self.generate_metadata(record, pdf_type, fetch_result)

        # Store in multi-cloud storage
        storage_key = f"{record.nct_id}/{pdf_type}/{fetch_result.pdf_path.name}"

        try:
            storage_result = await storage_manager.store(
                file_path=fetch_result.pdf_path,
                key=storage_key,
                metadata=metadata,
                content_type="application/pdf",
            )

            if storage_result.success:
                logger.info(
                    f"Successfully stored {storage_key} in {storage_result.provider}"
                )
                # Add storage metadata
                metadata["storage_provider"] = storage_result.provider
                metadata["storage_path"] = storage_result.path
                metadata["storage_etag"] = storage_result.etag
                return metadata
            else:
                logger.error(
                    f"Failed to store {storage_key}: {storage_result.error}"
                )
                return None

        except Exception as e:
            logger.error(f"Error storing {storage_key}: {e}")
            return None


if __name__ == "__main__":
    """
    CLI entry point for testing the ClinicalTrialsFetcher.

    Usage:
        python clinical_trials_pdf.py --source clinical_trials --help
        python clinical_trials_pdf.py --source clinical_trials search "cancer"
        python clinical_trials_pdf.py --source clinical_trials fetch NCT1234567 protocol
    """
    import argparse
    import sys
    try:
        from src.config_loader import load_source_config
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from src.config_loader import load_source_config

    parser = argparse.ArgumentParser(
        description="ClinicalTrials.gov PDF Fetcher - ALL config-driven"
    )
    parser.add_argument(
        "--source",
        type=str,
        default="clinical_trials",
        help="Source name in config/app.yaml",
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=["search", "fetch", "validate"],
        help="Command to run",
    )
    parser.add_argument(
        "args",
        nargs="*",
        help="Command arguments",
    )

    args = parser.parse_args()

    # Load config from YAML
    print(f"Loading source config: {args.source}")
    config = load_source_config(args.source)

    # Show config summary
    print("\n=== Configuration Summary (ALL from YAML) ===")
    print(f"Name: {config.get('name')}")
    print(f"API Base URL: {config.get('api', {}).get('base_url')}")
    print(f"Search Endpoint: {config.get('api', {}).get('search_endpoint')}")
    print(f"Rate Limit: {config.get('rate_limit', {}).get('calls_per_minute')} calls/min")
    print(f"Max Studies: {config.get('search', {}).get('max_studies_per_query')}")
    print(f"Search Fields: {config.get('search', {}).get('fields')}")
    print(f"PDF Patterns: {list(config.get('api', {}).get('pdf_patterns', {}).keys())}")
    print(f"Storage Primary: {config.get('storage', {}).get('primary', {}).get('provider')}")
    print(f"Storage Fallback: {config.get('storage', {}).get('fallback', {}).get('provider')}")
    print(f"Metadata Fields: {config.get('metadata', {}).get('include_fields')}")
    print("============================================\n")

    if args.command == "validate":
        print("Validating config...")
        try:
            fetcher = ClinicalTrialsFetcher(config)
            print("✓ Config is valid!")
        except ValueError as e:
            print(f"✗ Config validation failed: {e}")
            sys.exit(1)

    elif args.command == "search":
        query = args.args[0] if args.args else config.get("search", {}).get("default_query")
        max_results = int(args.args[1]) if len(args.args) > 1 else None

        async def run_search():
            fetcher = ClinicalTrialsFetcher(config)
            try:
                results = await fetcher.search(query, max_results)
                print(f"\nFound {len(results)} studies:")
                for r in results[:5]:
                    print(f"  - {r.nct_id}: {r.brief_title}")
                if len(results) > 5:
                    print(f"  ... and {len(results) - 5} more")
            finally:
                await fetcher.close()

        asyncio.run(run_search())

    elif args.command == "fetch":
        if len(args.args) < 2:
            print("Usage: fetch <nct_id> <pdf_type>")
            sys.exit(1)

        nct_id = args.args[0]
        pdf_type = args.args[1]

        async def run_fetch():
            fetcher = ClinicalTrialsFetcher(config)
            try:
                result = await fetcher.fetch_pdf(nct_id, pdf_type)
                if result and result.success:
                    print(f"✓ Downloaded: {result.pdf_path} ({result.file_size_bytes} bytes)")
                else:
                    print(f"✗ Fetch failed: {result.error if result else 'Unknown error'}")
            finally:
                await fetcher.close()

        asyncio.run(run_fetch())

    else:
        parser.print_help()
