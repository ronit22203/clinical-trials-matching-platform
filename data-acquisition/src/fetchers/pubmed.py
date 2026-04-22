"""
PubMed Central (PMC) PDF fetcher implementation.

Fetches open-access full-text PDFs from PubMed Central via NCBI E-utilities:
  1. esearch  → list of PMC IDs matching the query
  2. esummary → article metadata (title, journal, authors, doi, pubdate)
  3. PDF download from https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{id}/pdf/

ALL values come from config/app.yaml → data_acquisition.sources.pubmed — nothing hardcoded here.
"""

import asyncio
import io
import logging
import os
import tarfile
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

try:
    from .base import BaseFetcher, FetchResult, SearchRecord
except ImportError:
    from base import BaseFetcher, FetchResult, SearchRecord

logger = logging.getLogger(__name__)


class PubMedFetcher(BaseFetcher):
    """
    PubMed Central implementation of BaseFetcher.

    Uses NCBI E-utilities (esearch + esummary) for search,
    and the PMC PDF URL pattern for downloads.
    """

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self._client: Optional[httpx.AsyncClient] = None
        self._last_call_time: float = 0.0
        self._calls_this_minute: int = 0
        self._minute_start: float = time.time()

        self._validate_config()

        api_cfg = self.api_config
        self.base_url: str = api_cfg["base_url"]
        self.search_endpoint: str = api_cfg["search_endpoint"]
        self.summary_endpoint: str = api_cfg["summary_endpoint"]
        self.pdf_patterns: dict[str, str] = api_cfg["pdf_patterns"]
        self.oa_service_url: str = api_cfg["oa_service_url"]
        self.ftp_https_mirror: str = api_cfg["ftp_https_mirror"]
        self.min_pdf_bytes: int = api_cfg.get("min_pdf_bytes", 51200)
        self.timeout_seconds: int = api_cfg["timeout_seconds"]
        self.max_retries: int = api_cfg["max_retries"]
        self.user_agent: str = api_cfg["user_agent"]

        # Optional NCBI API key — raises rate limit from 3 → 10 req/s
        api_key_env: str = api_cfg.get("api_key_env", "NCBI_API_KEY")
        self.api_key: Optional[str] = os.environ.get(api_key_env)

        rate_cfg = self.rate_limit_config
        self.calls_per_minute: int = rate_cfg["calls_per_minute"]
        self.concurrency: int = rate_cfg["concurrency"]

        search_cfg = self.config.get("search", {})
        self.db: str = search_cfg["db"]
        self.max_studies_per_query: int = search_cfg["max_studies_per_query"]
        self.open_access_filter: str = search_cfg.get("open_access_filter", "")

    def _validate_config(self) -> None:
        required_sections = ["api", "rate_limit", "storage", "metadata"]
        missing = [s for s in required_sections if s not in self.config]
        if missing:
            raise ValueError(f"Missing required config sections: {missing}")

        api_required = [
            "base_url", "search_endpoint", "summary_endpoint",
            "pdf_patterns", "timeout_seconds", "max_retries", "user_agent",
        ]
        api_missing = [k for k in api_required if k not in self.api_config]
        if api_missing:
            raise ValueError(f"Missing required API config: {api_missing}")

        if "db" not in self.config.get("search", {}):
            raise ValueError("Missing required search config: db")

        logger.info(f"Config validated for {self.name}")

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_seconds),
                headers={"User-Agent": self.user_agent},
                follow_redirects=True,
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _enforce_rate_limit(self) -> None:
        current = time.time()
        if current - self._minute_start >= 60:
            self._calls_this_minute = 0
            self._minute_start = current

        if self._calls_this_minute >= self.calls_per_minute:
            sleep_for = 60 - (current - self._minute_start)
            if sleep_for > 0:
                logger.debug(f"Rate limit reached, sleeping {sleep_for:.2f}s")
                await asyncio.sleep(sleep_for)
                self._calls_this_minute = 0
                self._minute_start = time.time()

        elapsed = current - self._last_call_time
        min_interval = 60.0 / self.calls_per_minute
        if elapsed < min_interval:
            await asyncio.sleep(min_interval - elapsed)

        self._calls_this_minute += 1
        self._last_call_time = time.time()

    def _eutils_params(self, extra: dict[str, Any]) -> dict[str, Any]:
        """Build base E-utilities params, injecting API key if available."""
        params: dict[str, Any] = {"retmode": "json"}
        if self.api_key:
            params["api_key"] = self.api_key
        params.update(extra)
        return params

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(httpx.HTTPError),
    )
    async def search(
        self, query: str, max_results: Optional[int] = None
    ) -> list[SearchRecord]:
        """
        Search PMC for open-access articles matching query.

        Args:
            query: Free-text search query
            max_results: Max results (defaults to search.max_studies_per_query in config)

        Returns:
            List of SearchRecord objects, each representing one PMC article
        """
        if max_results is None:
            max_results = self.max_studies_per_query

        # Append open-access filter from config
        full_query = query
        if self.open_access_filter:
            full_query = f"{query} AND {self.open_access_filter}"

        client = await self._get_client()
        await self._enforce_rate_limit()

        # Step 1: esearch — get PMC IDs
        search_url = f"{self.base_url}{self.search_endpoint}"
        search_params = self._eutils_params({
            "db": self.db,
            "term": full_query,
            "retmax": max_results,
        })

        logger.info(f"Searching PMC: '{query}' (max {max_results})")

        response = await client.get(search_url, params=search_params)
        response.raise_for_status()

        result = response.json().get("esearchresult", {})
        pmc_ids: list[str] = result.get("idlist", [])

        if not pmc_ids:
            logger.info("No PMC articles found")
            return []

        logger.info(f"Found {len(pmc_ids)} PMC IDs — fetching summaries")

        # Step 2: esummary — get metadata for each article
        await self._enforce_rate_limit()
        summary_url = f"{self.base_url}{self.summary_endpoint}"
        summary_params = self._eutils_params({
            "db": self.db,
            "id": ",".join(pmc_ids),
        })

        sum_response = await client.get(summary_url, params=summary_params)
        sum_response.raise_for_status()

        sum_result = sum_response.json().get("result", {})

        records: list[SearchRecord] = []
        for pmc_id in sum_result.get("uids", []):
            article = sum_result.get(pmc_id, {})
            record = self._parse_article(pmc_id, article)
            if record:
                records.append(record)

        logger.info(f"Parsed {len(records)} records from PMC")
        return records

    def _parse_article(self, pmc_id: str, article: dict[str, Any]) -> Optional[SearchRecord]:
        """Parse an esummary article dict into a SearchRecord."""
        try:
            title = article.get("title", "")
            if not title:
                return None

            # Extract DOI from articleids list
            doi = next(
                (aid["value"] for aid in article.get("articleids", [])
                 if aid.get("idtype") == "doi"),
                None,
            )

            # Authors as comma-separated string for brief display
            authors = article.get("authors", [])
            lead_author = authors[0]["name"] if authors else None

            return SearchRecord(
                nct_id=pmc_id,           # PMC numeric ID (no "PMC" prefix)
                brief_title=title,
                official_title=title,
                overall_status="published",
                lead_sponsor_name=lead_author,
                study_type="journal_article",
                phase=article.get("source", ""),      # journal abbreviation
                enrollment_count=None,
                last_update_post_date=article.get("pubdate"),
                raw_data={
                    **article,
                    "doi": doi,
                    "fulljournalname": article.get("fulljournalname", ""),
                    "authors_list": [a["name"] for a in authors],
                },
            )
        except Exception as e:
            logger.warning(f"Failed to parse PMC article {pmc_id}: {e}")
            return None

    async def _get_oa_download(self, pmc_id: str) -> Optional[tuple[str, str]]:
        """
        Query the PMC Open Access service to get the actual download URL.

        Returns (format, url) where format is 'pdf' or 'tgz', or None if not OA.
        ftp:// hrefs are transparently converted to https:// via NCBI's HTTPS mirror.
        """
        client = await self._get_client()
        resp = await client.get(self.oa_service_url, params={"id": f"PMC{pmc_id}"})
        resp.raise_for_status()

        root = ET.fromstring(resp.text)
        if root.find(".//error") is not None:
            return None  # Not Open Access

        # Prefer direct PDF link; fall back to tarball
        links = root.findall(".//link")
        for preferred_fmt in ("pdf", "tgz"):
            for link in links:
                if link.get("format") == preferred_fmt:
                    href = link.get("href", "")
                    if href.startswith("ftp://"):
                        href = href.replace("ftp://ftp.ncbi.nlm.nih.gov", self.ftp_https_mirror, 1)
                    return (preferred_fmt, href)
        return None

    def _validate_pdf_bytes(self, data: bytes, pmc_id: str) -> Optional[str]:
        """Return error string if data is not a valid PDF, else None."""
        if not data.startswith(b"%PDF-"):
            return f"PMC{pmc_id}: not a PDF (magic bytes: {data[:8]!r})"
        if len(data) < self.min_pdf_bytes:
            return f"PMC{pmc_id}: file too small ({len(data):,} bytes < {self.min_pdf_bytes:,} minimum)"
        return None

    async def fetch_pdf(
        self,
        nct_id: str,      # PMC numeric ID
        pdf_type: str = "fulltext",
        temp_dir: Optional[Path] = None,
    ) -> Optional[FetchResult]:
        """
        Download a PDF from PMC via the OA service (guaranteed open-access link).

        Flow:
          1. PMC OA service → get actual download URL (raises error if not OA)
          2. If format=tgz: download tarball, extract first .pdf inside
          3. If format=pdf: download directly
          4. Validate: must start with %PDF- and be >= min_pdf_bytes
        """
        if temp_dir is None:
            temp_dir = Path("/tmp/pubmed")
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_file = temp_dir / f"PMC{nct_id}_{pdf_type}.pdf"

        logger.info(f"Fetching PMC{nct_id} [{pdf_type}]")

        try:
            await self._enforce_rate_limit()

            # Step 1 — check OA service for the real download URL
            oa = await self._get_oa_download(nct_id)
            if oa is None:
                logger.info(f"PMC{nct_id}: not Open Access — skipping")
                return FetchResult(
                    nct_id=nct_id, pdf_type=pdf_type, pdf_path=temp_file,
                    success=False, error="Not Open Access (OA service)",
                )

            fmt, download_url = oa
            logger.info(f"PMC{nct_id}: OA link ({fmt}): {download_url}")

            client = await self._get_client()
            await self._enforce_rate_limit()
            response = await client.get(download_url)

            if response.status_code == 404:
                logger.info(f"PMC{nct_id}: OA link returned 404")
                return FetchResult(
                    nct_id=nct_id, pdf_type=pdf_type, pdf_path=temp_file,
                    success=False, error="OA link 404",
                )
            response.raise_for_status()

            # Step 2 — extract or use directly
            if fmt == "tgz":
                archive = tarfile.open(fileobj=io.BytesIO(response.content))
                pdf_member = next(
                    (m for m in archive.getmembers() if m.name.endswith(".pdf")), None
                )
                if pdf_member is None:
                    return FetchResult(
                        nct_id=nct_id, pdf_type=pdf_type, pdf_path=temp_file,
                        success=False, error="No PDF found inside tarball",
                    )
                pdf_bytes = archive.extractfile(pdf_member).read()
            else:
                pdf_bytes = response.content

            # Step 3 — validate
            err = self._validate_pdf_bytes(pdf_bytes, nct_id)
            if err:
                logger.error(err)
                return FetchResult(
                    nct_id=nct_id, pdf_type=pdf_type, pdf_path=temp_file,
                    success=False, error=err,
                )

            temp_file.write_bytes(pdf_bytes)
            file_size = temp_file.stat().st_size
            self._track_temp_file(temp_file)

            logger.info(f"PMC{nct_id}: downloaded {file_size:,} bytes ✓")

            return FetchResult(
                nct_id=nct_id, pdf_type=pdf_type, pdf_path=temp_file,
                success=True, file_size_bytes=file_size,
            )

        except httpx.HTTPStatusError as e:
            logger.error(f"PMC{nct_id}: HTTP error: {e}")
            return FetchResult(
                nct_id=nct_id, pdf_type=pdf_type, pdf_path=temp_file,
                success=False, error=str(e),
            )
        except Exception as e:
            logger.error(f"PMC{nct_id}: unexpected error: {e}")
            return FetchResult(
                nct_id=nct_id, pdf_type=pdf_type, pdf_path=temp_file,
                success=False, error=str(e),
            )

    def generate_metadata(
        self,
        record: SearchRecord,
        pdf_type: str,
        fetch_result: FetchResult,
    ) -> dict[str, Any]:
        """Generate metadata sidecar for a fetched PMC article."""
        metadata_cfg = self.config.get("metadata", {})
        raw = record.raw_data

        metadata: dict[str, Any] = {
            "pmcid": f"PMC{record.nct_id}",
            "title": record.brief_title,
            "journal": raw.get("fulljournalname", record.phase),
            "authors": raw.get("authors_list", []),
            "pubdate": record.last_update_post_date,
            "doi": raw.get("doi"),
        }

        # Custom fields from config
        custom = metadata_cfg.get("custom_fields", [])
        if "fetched_at" in custom:
            metadata["fetched_at"] = datetime.utcnow().isoformat()
        if "source_version" in custom:
            metadata["source_version"] = metadata_cfg.get("version", "1.0")
        if "pdf_type" in custom:
            metadata["pdf_type"] = pdf_type
        if "processing_tier" in custom:
            metadata["processing_tier"] = "primary"

        metadata["file_size_bytes"] = fetch_result.file_size_bytes
        metadata["fallback_used"] = fetch_result.fallback_used
        metadata["source_url"] = self._format_url(
            self.pdf_patterns.get(pdf_type, ""), record.nct_id
        )

        return metadata
