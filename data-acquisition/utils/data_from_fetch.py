#!/usr/bin/env python3
"""
data_from_fetch.py — Parse pipeline.log and output comprehensive fetch results.

Extracts every available detail from the fetch pipeline log including:
- Per-document: ID, source URL, temp hash, HTTP status, size, real download/upload
  timing, storage paths, query, trace ID, keyword index, arXiv search query
- Unavailable documents (404 / not Open Access) as first-class records
- Warnings emitted during the run
- Per-query breakdown: arXiv query, total results, records found, succeeded,
  new-unique vs duplicate, not-available, failed, bytes, duration, manifest path
- Global run config (target, per_keyword, delay, dry_run, total keywords)
- Global summary (total unique PDFs, keywords exhausted, shortfall warning)
- Aggregate statistics: file-size distribution (avg/median/min/max), real
  download & upload throughput, deduplication rate, p95 timing

Usage:
    python utils/data_from_fetch.py                          # Full report
    python utils/data_from_fetch.py --stats                  # Statistics only
    python utils/data_from_fetch.py --export json            # Export to JSON
    python utils/data_from_fetch.py --export csv             # Export to CSV
    python utils/data_from_fetch.py --export markdown        # Markdown report
    python utils/data_from_fetch.py --query "cancer"         # Filter by query
    python utils/data_from_fetch.py --top 10                 # Top 10 largest
    python utils/data_from_fetch.py --unavailable            # Show 404 docs
    python utils/data_from_fetch.py --warnings               # Show warnings
    python utils/data_from_fetch.py --by-keyword             # Per-keyword table
    python utils/data_from_fetch.py --verbose                # All sections
"""

import argparse
import csv
import json
import re
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass, asdict
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Optional


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOG_PATH = PROJECT_ROOT / "logs" / "pipeline.log"


# ── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class DocumentRecord:
    """A successfully fetched and stored document."""
    arxiv_id: str
    pdf_type: str
    file_size_bytes: int
    download_duration_s: float      # actual time from ↓ line
    upload_duration_s: float        # total − download
    total_duration_s: float         # from ✓ line
    storage_provider: str
    pdf_storage_path: str
    metadata_storage_path: str
    source_url: str                 # https://arxiv.org/pdf/…
    temp_filename: str              # md5hash.pdf local temp file
    http_status: int                # HTTP response code (200, etc.)
    query: str
    trace_id: str
    keyword_index: str              # "3/54"
    arxiv_search_query: str         # verbatim arXiv query string
    timestamp: str                  # HH:MM:SS fetch start
    status: str = "success"


@dataclass
class UnavailableRecord:
    """A document that was unavailable (404 / not Open Access)."""
    arxiv_id: str
    pdf_type: str
    reason: str                     # "404"
    query: str
    trace_id: str
    keyword_index: str
    timestamp: str


@dataclass
class WarningRecord:
    """A WARNING-level log line."""
    message: str
    logger: str
    timestamp: str
    trace_id: str


@dataclass
class QuerySummary:
    """Per-query-batch statistics."""
    query: str
    trace_id: str
    keyword_index: str
    arxiv_search_query: str
    arxiv_total_results: int        # "100 of N total results"
    arxiv_records_found: int        # "Found N bioRxiv records"
    max_pdfs: int
    total_documents: int            # Attempted
    succeeded: int                  # Uploaded OK
    new_documents: int              # Deduplicated new uploads
    duplicate_documents: int        # Already in S3 from prior batch
    not_available: int              # 404 / not OA
    failed: int                     # Real errors
    total_bytes: int
    total_duration_s: float
    avg_duration_s: float
    manifest_path: str


@dataclass
class GlobalRunConfig:
    """Program-level configuration from the log header."""
    source: str
    target_pdfs: int
    per_keyword: int
    delay_s: float
    dry_run: bool
    total_keywords: int


@dataclass
class GlobalSummary:
    """Final run-level summary from program footer."""
    total_unique_pdfs: int
    unique_arxiv_ids: int
    keywords_exhausted: bool
    warning_message: str            # e.g. "Only reached 461/500"


@dataclass
class PipelineStatistics:
    """Aggregated statistics across the entire run."""
    # Counts
    total_queries: int
    total_documents: int
    total_succeeded: int
    total_new_unique: int
    total_duplicates: int
    total_not_available: int
    total_failed: int
    total_warnings: int
    success_rate: str
    deduplication_rate: str
    # File sizes
    total_bytes: int
    total_mb: float
    avg_file_size_bytes: float
    median_file_size_bytes: float
    min_file_size_bytes: int
    max_file_size_bytes: int
    # Timing
    total_download_time_s: float
    total_upload_time_s: float
    total_pipeline_time_s: float
    avg_doc_download_time_s: float
    avg_doc_upload_time_s: float
    median_doc_download_time_s: float
    p95_doc_download_time_s: float
    # Throughput
    avg_download_throughput_mbps: float
    avg_upload_throughput_mbps: float
    # Storage
    storage_providers: dict
    # Query breakdown list
    queries: list
    # Global metadata
    run_config: dict
    global_summary: dict


# ── LogParser ─────────────────────────────────────────────────────────────────

class LogParser:
    """
    Single-pass line-by-line parser for pipeline.log.

    State machine tracks:  current query header → per-doc lifecycle → summary block
    """

    def __init__(self, log_path: Path):
        self.log_path = log_path
        self.documents: list[DocumentRecord] = []
        self.unavailable: list[UnavailableRecord] = []
        self.warnings: list[WarningRecord] = []
        self.query_summaries: list[QuerySummary] = []
        self.run_config: Optional[GlobalRunConfig] = None
        self.global_summary: Optional[GlobalSummary] = None

        # ── Per-query state ──────────────────────────────────────────
        self._current_query: str = ""
        self._current_trace_id: str = ""
        self._current_pdf_type: str = "paper"
        self._current_keyword_index: str = ""
        self._current_arxiv_search_query: str = ""
        self._current_arxiv_total_results: int = 0
        self._current_arxiv_records_found: int = 0
        self._current_max_pdfs: int = 0
        self._current_manifest_path: str = ""

        # ── Per-document state ───────────────────────────────────────
        self._doc: Optional[dict] = None

        # ── Summary-block state ──────────────────────────────────────
        self._in_summary: bool = False
        self._summary: dict = {}

        # ── Global-footer state ──────────────────────────────────────
        self._in_global: bool = False
        self._global: dict = {}

        # ── Program-header accumulator ───────────────────────────────
        self._hdr: dict = {}

    # ── Public API ────────────────────────────────────────────────────────────

    def parse(self, manifest_dir: Optional[Path] = None, source_filter: Optional[str] = None):
        if not self.log_path.exists():
            raise FileNotFoundError(f"Log file not found: {self.log_path}")

        with open(self.log_path, encoding="utf-8") as f:
            for line in f:
                self._process(line)

        # Build global objects if not yet finalised
        if self._global:
            self._build_global_summary()

        # Augment with manifest data (covers runs where subprocess output wasn't logged)
        if manifest_dir is None:
            manifest_dir = self.log_path.parent.parent / "temp" / "manifests"
        existing_trace_ids = {qs.trace_id for qs in self.query_summaries}
        loader = ManifestLoader(manifest_dir, source_filter)
        m_docs, m_unavail, m_qs = loader.load(existing_trace_ids)
        self.documents.extend(m_docs)
        self.unavailable.extend(m_unavail)
        self.query_summaries.extend(m_qs)

        return (
            self.documents,
            self.unavailable,
            self.warnings,
            self.query_summaries,
            self.run_config,
            self.global_summary,
        )

    # ── Line dispatcher ───────────────────────────────────────────────────────

    def _process(self, line: str):
        s = line.strip()
        if not s:
            return
        ts = self._ts(line)

        # ── Global footer ─────────────────────────────────────────────
        if "Finished." in s:
            self._in_global = True
            return

        if self._in_global:
            self._parse_global_line(s)
            return

        if "⚠" in s or ("Only reached" in s and "/" in s):
            self._global.setdefault("warning_message", s)
            if not self.global_summary:
                self._build_global_summary()
            return

        # ── Program header ────────────────────────────────────────────
        if ("bioRxiv bulk fetch" in s or "medRxiv bulk fetch" in s) and "target" in s:
            m = re.search(r"target (\d+) PDFs", s)
            if m:
                self._hdr["target_pdfs"] = int(m.group(1))
            return

        if "per_keyword=" in s and "delay=" in s:
            for pat, key, typ in [
                (r"per_keyword=(\d+)", "per_keyword", int),
                (r"delay=([\d.]+)s", "delay_s", float),
                (r"dry_run=(\w+)", "dry_run", str),
            ]:
                m = re.search(pat, s)
                if m:
                    val = m.group(1)
                    self._hdr[key] = (val.lower() == "true") if key == "dry_run" else typ(val)
            return

        # ── Keyword progress header  [  N/M] 'query' … ───────────────
        m = re.search(r"\[\s*(\d+)/(\d+)\]\s+'(.+?)'", s)
        if m:
            self._current_keyword_index = f"{m.group(1)}/{m.group(2)}"
            self._hdr.setdefault("total_keywords", int(m.group(2)))
            return

        # ── Query header fields (inside ======= block) ────────────────
        if "trace_id  :" in line:
            m = re.search(r"trace_id\s*:\s*(\S+)", line)
            if m:
                self._current_trace_id = m.group(1)
            return

        if "source    :" in line:
            m = re.search(r"source\s*:\s*(\S+)", line)
            if m:
                self._hdr.setdefault("source", m.group(1))
            return

        if "query     :" in line:
            m = re.search(r"query\s*:\s*(.+)", line)
            if m:
                self._current_query = m.group(1).strip()
                self._maybe_build_run_config()
            return

        if "max_pdfs  :" in line:
            m = re.search(r"max_pdfs\s*:\s*(\d+)", line)
            if m:
                self._current_max_pdfs = int(m.group(1))
            return

        if "pdf_types :" in line:
            m = re.search(r"\['(\w+)'\]", line)
            if m:
                self._current_pdf_type = m.group(1)
            return

        # ── arXiv search info ─────────────────────────────────────────
        if "Searching arXiv:" in line:
            m = re.search(r"Searching arXiv:\s*(.+?)(?:\s*\(max \d+\))?\s*$", line)
            if m:
                self._current_arxiv_search_query = m.group(1).strip()
            return

        if "Searching medRxiv" in line:
            m = re.search(r"Searching medRxiv \[(.+?) → .+?\] keywords=(.+?) \(max", line)
            if m:
                self._current_arxiv_search_query = f"medRxiv [{m.group(1)}] kw={m.group(2)}"
            return

        if "Got first page:" in line:
            m = re.search(r"Got first page:\s*\d+ of (\d+) total results", line)
            if m:
                self._current_arxiv_total_results = int(m.group(1))
            return

        if "Found" in line and ("bioRxiv records" in line or "medRxiv records" in line):
            m = re.search(r"Found (\d+) (?:bio|med)Rxiv records", line)
            if m:
                self._current_arxiv_records_found = int(m.group(1))
            return

        # ── Fetch lifecycle ───────────────────────────────────────────
        if ("src.fetchers.biorxiv" in line or "src.fetchers.medrxiv" in line) and "Fetching PDF for" in line:
            m = re.search(r"Fetching PDF for (\S+) from (https?://\S+)", line)
            if m:
                self._doc = {
                    "arxiv_id": m.group(1),
                    "source_url": m.group(2),
                    "timestamp": ts,
                    "pdf_type": self._current_pdf_type,
                    "http_status": 0,
                    "temp_filename": "",
                    "file_size_bytes": 0,
                    "download_duration_s": 0.0,
                    "pdf_storage_path": "",
                    "metadata_storage_path": "",
                }
            return

        if self._doc and "httpx" in line and "HTTP Request:" in line:
            m = re.search(r'"HTTP/[\d.]+ (\d+)', line)
            if m:
                self._doc["http_status"] = int(m.group(1))
            return

        if self._doc and ("src.fetchers.biorxiv" in line or "src.fetchers.medrxiv" in line) and "Downloaded" in line:
            m = re.search(r"Downloaded \S+ → (\S+\.pdf) \((\d+) bytes\)", line)
            if m:
                self._doc["temp_filename"] = m.group(1)
                self._doc["file_size_bytes"] = int(m.group(2))
            return

        # ↓ download summary — gives us the real download duration
        if "fetch_pdfs" in line and "↓" in line:
            m = re.search(r"↓\s+(\S+)\s+\[(\w+)\]\s+([\d,]+) bytes\s+\(([\d.]+)s\)", line)
            if m and self._doc and self._doc.get("arxiv_id") == m.group(1):
                self._doc["download_duration_s"] = float(m.group(4))
                if not self._doc.get("file_size_bytes"):
                    self._doc["file_size_bytes"] = int(m.group(3).replace(",", ""))
            return

        if self._doc and "src.storage.aws" in line and "Uploaded" in line and ".pdf" in line and "metadata" not in line:
            m = re.search(r"Uploaded (raw/\S+\.pdf)", line)
            if m:
                self._doc["pdf_storage_path"] = m.group(1)
            return

        if self._doc and "src.storage.aws" in line and "Uploaded metadata to" in line:
            m = re.search(r"Uploaded metadata to (raw/\S+\.metadata\.json)", line)
            if m:
                self._doc["metadata_storage_path"] = m.group(1)
            return

        # ✓ total-time line — finalise document
        if "fetch_pdfs" in line and "✓" in line and "→" in line:
            m = re.search(r"✓\s+(\S+)\s+\[(\w+)\]\s+→\s+(\S+)\s+\(([\d.]+)s\)", line)
            if m and self._doc:
                total = float(m.group(4))
                dl = self._doc.get("download_duration_s", 0.0)
                self._doc["total_duration_s"] = total
                self._doc["upload_duration_s"] = round(max(total - dl, 0.0), 3)
                self._doc["storage_provider"] = m.group(3)
                self._finalise_doc()
            return

        # ⊘ unavailable
        if "fetch_pdfs" in line and "⊘" in line and "not available" in line:
            m = re.search(r"⊘\s+(\S+)\s+\[(\w+)\]\s+not available\s+\((\w+)\)", line)
            if m:
                self.unavailable.append(UnavailableRecord(
                    arxiv_id=m.group(1),
                    pdf_type=m.group(2),
                    reason=m.group(3),
                    query=self._current_query,
                    trace_id=self._current_trace_id,
                    keyword_index=self._current_keyword_index,
                    timestamp=ts,
                ))
            self._doc = None
            return

        # WARNING lines
        if "WARNING" in line:
            m = re.search(r"WARNING\s+(\S+)\s+(.+)", line)
            if m:
                self.warnings.append(WarningRecord(
                    message=m.group(2).strip(),
                    logger=m.group(1),
                    timestamp=ts,
                    trace_id=self._current_trace_id,
                ))
            return

        # ── Manifest path ─────────────────────────────────────────────
        if "Manifest" in line and "temp/manifests/" in line:
            m = re.search(r"Manifest\s*:\s*(temp/manifests/\S+)", line)
            if m:
                self._current_manifest_path = m.group(1)
                # Back-fill last summary if it was just finalised without manifest
                if self.query_summaries and not self.query_summaries[-1].manifest_path:
                    self.query_summaries[-1].manifest_path = m.group(1)
            return

        # ── Batch progress: ✓ N new | ⊘ N | ✗ N | total so far: N ───
        if "✓" in line and "new" in line and "total so far:" in line:
            m = re.search(
                r"✓\s+(\d+)\s+new\s+\|\s+⊘\s+(\d+)\s+unavailable\s+\|\s+✗\s+(\d+)\s+errors"
                r"\s+\|\s+total so far:\s+(\d+)",
                line,
            )
            if m and self.query_summaries:
                new = int(m.group(1))
                last = self.query_summaries[-1]
                last.new_documents = new
                last.duplicate_documents = max(last.succeeded - new, 0)
            return

        # ── Query summary block ───────────────────────────────────────
        if self._in_summary:
            self._parse_summary_line(s)
            return

        if "Done in" in line and ":" in line:
            m = re.search(r"Done in\s*:\s*([\d.]+)s", line)
            if m:
                self._in_summary = True
                self._summary = {"duration": float(m.group(1))}
            return

    # ── Summary block parser ──────────────────────────────────────────────────

    def _parse_summary_line(self, s: str):
        if "Succeeded" in s:
            m = re.search(r"Succeeded\s*:\s*(\d+)", s)
            if m:
                self._summary["succeeded"] = int(m.group(1))
        elif "Not available" in s:
            m = re.search(r"Not available\s*:\s*(\d+)", s)
            if m:
                self._summary["not_available"] = int(m.group(1))
        elif "Failed" in s:
            m = re.search(r"Failed\s*:\s*(\d+)", s)
            if m:
                self._summary["failed"] = int(m.group(1))
        elif re.search(r"^Total\s*:\s*\d+", s) and "unique" not in s.lower():
            m = re.search(r"Total\s*:\s*(\d+)", s)
            if m:
                self._summary["total"] = int(m.group(1))
                self._finalise_query_summary()
                self._in_summary = False
                self._summary = {}

    # ── Global footer parser ──────────────────────────────────────────────────

    def _parse_global_line(self, s: str):
        if "Total unique PDFs fetched" in s or "New unique PDFs fetched" in s:
            m = re.search(r"(?:Total|New) unique PDFs fetched\s*:\s*(\d+)", s)
            if m:
                self._global["total_unique_pdfs"] = int(m.group(1))
        elif "Unique arxiv IDs" in s or "Total known DOIs now" in s:
            m = re.search(r"(?:Unique arxiv IDs|Total known DOIs now)\s*:\s*(\d+)", s)
            if m:
                self._global["unique_arxiv_ids"] = int(m.group(1))
        elif "Keywords exhausted" in s:
            m = re.search(r"Keywords exhausted\s*:\s*(\w+)", s)
            if m:
                self._global["keywords_exhausted"] = (m.group(1).lower() == "true")
            self._in_global = False
            self._build_global_summary()
        elif "=====" in s and self._global:
            self._in_global = False
            self._build_global_summary()

    # ── Finalise helpers ──────────────────────────────────────────────────────

    def _finalise_doc(self):
        d = self._doc
        if not d or not d.get("pdf_storage_path"):
            self._doc = None
            return
        self.documents.append(DocumentRecord(
            arxiv_id=d.get("arxiv_id", ""),
            pdf_type=d.get("pdf_type", "paper"),
            file_size_bytes=d.get("file_size_bytes", 0),
            download_duration_s=round(d.get("download_duration_s", 0.0), 3),
            upload_duration_s=round(d.get("upload_duration_s", 0.0), 3),
            total_duration_s=round(d.get("total_duration_s", 0.0), 3),
            storage_provider=d.get("storage_provider", "aws_s3"),
            pdf_storage_path=d.get("pdf_storage_path", ""),
            metadata_storage_path=d.get("metadata_storage_path", ""),
            source_url=d.get("source_url", ""),
            temp_filename=d.get("temp_filename", ""),
            http_status=d.get("http_status", 0),
            query=self._current_query,
            trace_id=self._current_trace_id,
            keyword_index=self._current_keyword_index,
            arxiv_search_query=self._current_arxiv_search_query,
            timestamp=d.get("timestamp", ""),
            status="success",
        ))
        self._doc = None

    def _finalise_query_summary(self):
        sd = self._summary
        succeeded = sd.get("succeeded", 0)
        total = sd.get("total", 0)
        duration = sd.get("duration", 0.0)

        query_docs = [d for d in self.documents if d.trace_id == self._current_trace_id]
        total_bytes = sum(d.file_size_bytes for d in query_docs)

        self.query_summaries.append(QuerySummary(
            query=self._current_query,
            trace_id=self._current_trace_id,
            keyword_index=self._current_keyword_index,
            arxiv_search_query=self._current_arxiv_search_query,
            arxiv_total_results=self._current_arxiv_total_results,
            arxiv_records_found=self._current_arxiv_records_found,
            max_pdfs=self._current_max_pdfs,
            total_documents=total,
            succeeded=succeeded,
            new_documents=succeeded,      # updated by batch-progress line
            duplicate_documents=0,        # updated by batch-progress line
            not_available=sd.get("not_available", 0),
            failed=sd.get("failed", 0),
            total_bytes=total_bytes,
            total_duration_s=round(duration, 2),
            avg_duration_s=round(duration / total, 2) if total > 0 else 0.0,
            manifest_path=self._current_manifest_path,
        ))
        # Reset per-query accumulators
        self._current_arxiv_total_results = 0
        self._current_arxiv_records_found = 0
        self._current_manifest_path = ""

    def _maybe_build_run_config(self):
        if self.run_config:
            return
        if "per_keyword" in self._hdr and "target_pdfs" in self._hdr:
            self.run_config = GlobalRunConfig(
                source=self._hdr.get("source", "biorxiv"),
                target_pdfs=self._hdr.get("target_pdfs", 0),
                per_keyword=self._hdr.get("per_keyword", 0),
                delay_s=self._hdr.get("delay_s", 0.0),
                dry_run=self._hdr.get("dry_run", False),
                total_keywords=self._hdr.get("total_keywords", 0),
            )

    def _build_global_summary(self):
        new_total = self._global.get("total_unique_pdfs", 0)
        new_ids   = self._global.get("unique_arxiv_ids", 0)
        new_warn  = self._global.get("warning_message", "")
        new_exhausted = self._global.get("keywords_exhausted", False)

        if self.global_summary:
            # Accumulate across multiple runs (e.g. biorxiv then medrxiv)
            self.global_summary.total_unique_pdfs += new_total
            self.global_summary.unique_arxiv_ids  += new_ids
            self.global_summary.keywords_exhausted = new_exhausted
            if new_warn:
                sep = "\n" if self.global_summary.warning_message else ""
                self.global_summary.warning_message += sep + new_warn
        else:
            self.global_summary = GlobalSummary(
                total_unique_pdfs=new_total,
                unique_arxiv_ids=new_ids,
                keywords_exhausted=new_exhausted,
                warning_message=new_warn,
            )
        self._global = {}
        # Late-patch total_keywords into run_config if missing
        if self.run_config and not self.run_config.total_keywords:
            self.run_config.total_keywords = self._hdr.get("total_keywords", 0)

    @staticmethod
    def _ts(line: str) -> str:
        # Handles "HH:MM:SS" and "YYYY-MM-DD HH:MM:SS" prefixes
        m = re.match(r"^(?:\d{4}-\d{2}-\d{2}[T ])?(\d{2}:\d{2}:\d{2})", line)
        return m.group(1) if m else ""


# ── ManifestLoader ────────────────────────────────────────────────────────────

class ManifestLoader:
    """
    Loads per-document data from manifest JSON files written by fetch_pdfs.py.

    Manifest files (e.g. temp/manifests/medrxiv-bulk-*.json) contain the full
    result set for each keyword batch including file sizes, timing, and storage
    paths.  This supplements the log parser for runs where the subprocess output
    was not captured in pipeline.log.
    """

    def __init__(self, manifest_dir: Path, source_filter: Optional[str] = None):
        self.manifest_dir = manifest_dir
        self.source_filter = source_filter  # e.g. "medrxiv"; None = all

    def load(
        self,
        existing_trace_ids: set[str],
    ) -> tuple[list[DocumentRecord], list[UnavailableRecord], list[QuerySummary]]:
        """
        Read all manifests not already represented in existing_trace_ids.

        Returns (documents, unavailable, query_summaries).
        """
        documents: list[DocumentRecord] = []
        unavailable: list[UnavailableRecord] = []
        query_summaries: list[QuerySummary] = []

        if not self.manifest_dir.exists():
            return documents, unavailable, query_summaries

        pattern = "*.json" if not self.source_filter else f"*{self.source_filter}*.json"
        manifests = sorted(self.manifest_dir.glob(pattern))

        for path in manifests:
            try:
                with open(path) as f:
                    data = json.load(f)
            except Exception:
                continue

            trace_id = data.get("trace_id", "")
            source   = data.get("source", "")

            # Skip if already parsed from log, or wrong source filter
            if trace_id in existing_trace_ids:
                continue
            if self.source_filter and source != self.source_filter:
                continue

            query    = data.get("query", "")
            run_at   = data.get("run_at", "")[:19].replace("T", " ")  # "YYYY-MM-DD HH:MM:SS"
            # Derive keyword index from trace_id suffix (…-001, …-002)
            idx_m    = re.search(r"-(\d+)$", trace_id)
            kw_index = idx_m.group(1).lstrip("0") or "0" if idx_m else ""

            batch_docs: list[DocumentRecord] = []
            for r in data.get("results", []):
                nct_id   = r.get("nct_id", "")
                pdf_type = r.get("pdf_type", "paper")
                success  = r.get("success", False)

                if r.get("not_available"):
                    unavailable.append(UnavailableRecord(
                        arxiv_id=nct_id,
                        pdf_type=pdf_type,
                        reason=r.get("error", "404"),
                        query=query,
                        trace_id=trace_id,
                        keyword_index=kw_index,
                        timestamp=run_at,
                    ))
                    continue

                if not success:
                    continue

                fetch_s = float(r.get("fetch_seconds", 0))
                store_s = float(r.get("store_seconds", 0))
                size    = int(r.get("file_size_bytes", 0))
                path_   = r.get("storage_path", "")

                doc = DocumentRecord(
                    arxiv_id=nct_id,
                    pdf_type=pdf_type,
                    file_size_bytes=size,
                    download_duration_s=round(fetch_s, 3),
                    upload_duration_s=round(store_s, 3),
                    total_duration_s=round(fetch_s + store_s, 3),
                    storage_provider=r.get("storage_provider", "aws_s3"),
                    pdf_storage_path=path_,
                    metadata_storage_path=path_.replace(".pdf", ".metadata.json") if path_.endswith(".pdf") else "",
                    source_url=f"https://www.medrxiv.org/content/{nct_id}.full.pdf" if source == "medrxiv" else "",
                    temp_filename="",
                    http_status=200,
                    query=query,
                    trace_id=trace_id,
                    keyword_index=kw_index,
                    arxiv_search_query="",
                    timestamp=run_at,
                    status="success",
                )
                documents.append(doc)
                batch_docs.append(doc)

            total_bytes = sum(d.file_size_bytes for d in batch_docs)
            total_dur   = sum(d.total_duration_s for d in batch_docs)
            succeeded   = data.get("succeeded", 0)
            total_docs  = data.get("total", 0)

            query_summaries.append(QuerySummary(
                query=query,
                trace_id=trace_id,
                keyword_index=kw_index,
                arxiv_search_query="",
                arxiv_total_results=0,
                arxiv_records_found=total_docs,
                max_pdfs=total_docs,
                total_documents=total_docs,
                succeeded=succeeded,
                new_documents=succeeded,       # manifests don't track dedup
                duplicate_documents=0,
                not_available=data.get("not_available", 0),
                failed=data.get("failed", 0),
                total_bytes=total_bytes,
                total_duration_s=round(total_dur, 2),
                avg_duration_s=round(total_dur / total_docs, 2) if total_docs else 0.0,
                manifest_path=str(path.relative_to(PROJECT_ROOT)),
            ))

        return documents, unavailable, query_summaries


# ── ResultsAnalyzer ──────────────────────────────────────────────────────────

class ResultsAnalyzer:
    """Compute aggregate statistics from parsed records."""

    def __init__(
        self,
        documents: list[DocumentRecord],
        unavailable: list[UnavailableRecord],
        warnings: list[WarningRecord],
        query_summaries: list[QuerySummary],
        run_config: Optional[GlobalRunConfig],
        global_summary: Optional[GlobalSummary],
    ):
        self.documents = documents
        self.unavailable = unavailable
        self.warnings = warnings
        self.query_summaries = query_summaries
        self.run_config = run_config
        self.global_summary = global_summary

    def get_statistics(self) -> PipelineStatistics:
        docs = self.documents
        qs_list = self.query_summaries

        if not docs:
            return self._empty_stats()

        sizes = [d.file_size_bytes for d in docs]
        dl_times = [d.download_duration_s for d in docs]
        ul_times = [d.upload_duration_s for d in docs]

        total_bytes = sum(sizes)
        total_dl = sum(dl_times)
        total_ul = sum(ul_times)

        # Per-doc throughput (MB/s), guarded against zero
        dl_mbps = [
            (d.file_size_bytes / 1_048_576 / d.download_duration_s)
            for d in docs if d.download_duration_s > 0
        ]
        ul_mbps = [
            (d.file_size_bytes / 1_048_576 / d.upload_duration_s)
            for d in docs if d.upload_duration_s > 0
        ]

        total_new = sum(qs.new_documents for qs in qs_list)
        total_succeeded = sum(qs.succeeded for qs in qs_list)
        total_dups = total_succeeded - total_new

        providers: dict = defaultdict(int)
        for d in docs:
            providers[d.storage_provider] += 1

        query_stats = [
            {
                "keyword_index": qs.keyword_index,
                "query": qs.query,
                "trace_id": qs.trace_id,
                "search_query": qs.arxiv_search_query,
                "total_results_found": qs.arxiv_total_results,
                "records_found": qs.arxiv_records_found,
                "max_pdfs": qs.max_pdfs,
                "total_documents": qs.total_documents,
                "succeeded": qs.succeeded,
                "new_documents": qs.new_documents,
                "duplicate_documents": qs.duplicate_documents,
                "not_available": qs.not_available,
                "failed": qs.failed,
                "total_bytes": qs.total_bytes,
                "total_mb": round(qs.total_bytes / 1_048_576, 2),
                "duration_s": qs.total_duration_s,
                "avg_duration_s": qs.avg_duration_s,
                "manifest_path": qs.manifest_path,
            }
            for qs in qs_list
        ]

        n = len(docs)
        p95_idx = max(0, int(0.95 * n) - 1)

        return PipelineStatistics(
            total_queries=len(qs_list),
            total_documents=n,
            total_succeeded=total_succeeded,
            total_new_unique=total_new,
            total_duplicates=total_dups,
            total_not_available=sum(qs.not_available for qs in qs_list),
            total_failed=sum(qs.failed for qs in qs_list),
            total_warnings=len(self.warnings),
            success_rate=f"{total_succeeded / n * 100:.1f}%" if n else "0%",
            deduplication_rate=f"{total_dups / total_succeeded * 100:.1f}%" if total_succeeded else "0%",
            total_bytes=total_bytes,
            total_mb=round(total_bytes / 1_048_576, 2),
            avg_file_size_bytes=round(total_bytes / n, 0),
            median_file_size_bytes=round(statistics.median(sizes), 0),
            min_file_size_bytes=min(sizes),
            max_file_size_bytes=max(sizes),
            total_download_time_s=round(total_dl, 2),
            total_upload_time_s=round(total_ul, 2),
            total_pipeline_time_s=round(sum(qs.total_duration_s for qs in qs_list), 2),
            avg_doc_download_time_s=round(total_dl / n, 3),
            avg_doc_upload_time_s=round(total_ul / n, 3),
            median_doc_download_time_s=round(statistics.median(dl_times), 3),
            p95_doc_download_time_s=round(sorted(dl_times)[p95_idx], 3),
            avg_download_throughput_mbps=round(statistics.mean(dl_mbps), 2) if dl_mbps else 0.0,
            avg_upload_throughput_mbps=round(statistics.mean(ul_mbps), 2) if ul_mbps else 0.0,
            storage_providers=dict(providers),
            queries=query_stats,
            run_config=asdict(self.run_config) if self.run_config else {},
            global_summary=asdict(self.global_summary) if self.global_summary else {},
        )

    # Convenience filter helpers
    def get_documents_by_query(self, query: str) -> list[DocumentRecord]:
        return [d for d in self.documents if query.lower() in d.query.lower()]

    def get_top_largest(self, n: int) -> list[DocumentRecord]:
        return sorted(self.documents, key=lambda d: d.file_size_bytes, reverse=True)[:n]

    def get_slowest_downloads(self, n: int) -> list[DocumentRecord]:
        return sorted(self.documents, key=lambda d: d.download_duration_s, reverse=True)[:n]

    def get_slowest_uploads(self, n: int) -> list[DocumentRecord]:
        return sorted(self.documents, key=lambda d: d.upload_duration_s, reverse=True)[:n]

    def _empty_stats(self) -> PipelineStatistics:
        return PipelineStatistics(
            total_queries=0, total_documents=0, total_succeeded=0, total_new_unique=0,
            total_duplicates=0, total_not_available=0, total_failed=0, total_warnings=0,
            success_rate="0%", deduplication_rate="0%",
            total_bytes=0, total_mb=0, avg_file_size_bytes=0, median_file_size_bytes=0,
            min_file_size_bytes=0, max_file_size_bytes=0,
            total_download_time_s=0, total_upload_time_s=0, total_pipeline_time_s=0,
            avg_doc_download_time_s=0, avg_doc_upload_time_s=0,
            median_doc_download_time_s=0, p95_doc_download_time_s=0,
            avg_download_throughput_mbps=0, avg_upload_throughput_mbps=0,
            storage_providers={}, queries=[],
            run_config=asdict(self.run_config) if self.run_config else {},
            global_summary=asdict(self.global_summary) if self.global_summary else {},
        )


# ── ResultExporter ────────────────────────────────────────────────────────────

class ResultExporter:
    """Export results to JSON, CSV, or Markdown."""

    def __init__(
        self,
        documents: list[DocumentRecord],
        unavailable: list[UnavailableRecord],
        warnings: list[WarningRecord],
        stats: PipelineStatistics,
    ):
        self.documents = documents
        self.unavailable = unavailable
        self.warnings = warnings
        self.stats = stats

    def to_json(self, indent: int = 2) -> str:
        output = {
            "exported_at": datetime.now().isoformat(),
            "statistics": asdict(self.stats),
            "documents": [asdict(d) for d in self.documents],
            "unavailable": [asdict(u) for u in self.unavailable],
            "warnings": [asdict(w) for w in self.warnings],
        }
        return json.dumps(output, indent=indent, ensure_ascii=False)

    def to_csv(self) -> str:
        if not self.documents:
            return ""
        fieldnames = [
            "arxiv_id", "pdf_type", "file_size_bytes",
            "download_duration_s", "upload_duration_s", "total_duration_s",
            "storage_provider", "pdf_storage_path", "metadata_storage_path",
            "source_url", "temp_filename", "http_status",
            "query", "trace_id", "keyword_index", "arxiv_search_query",
            "timestamp", "status",
        ]
        out = StringIO()
        w = csv.DictWriter(out, fieldnames=fieldnames)
        w.writeheader()
        for d in self.documents:
            w.writerow(asdict(d))
        return out.getvalue()

    def to_markdown_report(self) -> str:
        s = self.stats
        lines = []

        lines += [
            "# Pipeline Fetch Results Report",
            f"\n*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
            "",
        ]

        # ── Run config & global summary ───────────────────────────────
        if s.run_config:
            rc = s.run_config
            lines += [
                "## ⚙️ Run Configuration",
                "",
                "| Parameter | Value |",
                "|-----------|-------|",
                f"| Source | `{rc.get('source', '?')}` |",
                f"| Target PDFs | {rc.get('target_pdfs', '?')} |",
                f"| Per Keyword | {rc.get('per_keyword', '?')} |",
                f"| Total Keywords | {rc.get('total_keywords', '?')} |",
                f"| Delay | {rc.get('delay_s', '?')}s |",
                f"| Dry Run | {rc.get('dry_run', '?')} |",
                "",
            ]

        if s.global_summary:
            gs = s.global_summary
            lines += [
                "## 🏁 Global Summary",
                "",
                "| Metric | Value |",
                "|--------|-------|",
                f"| Total Unique PDFs Fetched | **{gs.get('total_unique_pdfs', '?')}** |",
                f"| Unique Doc IDs | {gs.get('unique_arxiv_ids', '?')} |",
                f"| Keywords Exhausted | {gs.get('keywords_exhausted', '?')} |",
            ]
            if gs.get("warning_message"):
                lines.append(f"| ⚠️ Warning | {gs['warning_message']} |")
            lines.append("")

        # ── Counts summary ────────────────────────────────────────────
        lines += [
            "## 📊 Pipeline Summary",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Total Keyword Batches | {s.total_queries} |",
            f"| Total Documents Attempted | {s.total_documents} |",
            f"| Succeeded (total) | {s.total_succeeded} |",
            f"| **New Unique Uploads** | **{s.total_new_unique}** |",
            f"| Duplicate (already stored) | {s.total_duplicates} |",
            f"| Not Available (404) | {s.total_not_available} |",
            f"| Failed | {s.total_failed} |",
            f"| Warnings | {s.total_warnings} |",
            f"| Success Rate | {s.success_rate} |",
            f"| Deduplication Rate | {s.deduplication_rate} |",
            "",
        ]

        # ── Data volume ───────────────────────────────────────────────
        lines += [
            "## 💾 Data Volume",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Total | **{s.total_mb} MB** ({s.total_bytes:,} bytes) |",
            f"| Average File Size | {s.avg_file_size_bytes:,.0f} bytes |",
            f"| Median File Size | {s.median_file_size_bytes:,.0f} bytes |",
            f"| Min File Size | {s.min_file_size_bytes:,} bytes |",
            f"| Max File Size | {s.max_file_size_bytes:,} bytes |",
            "",
        ]

        # ── Timing & throughput ───────────────────────────────────────
        lines += [
            "## ⏱️ Timing & Throughput",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Total Download Time | {s.total_download_time_s:.2f}s |",
            f"| Total Upload Time | {s.total_upload_time_s:.2f}s |",
            f"| Total Pipeline Time | {s.total_pipeline_time_s:.2f}s |",
            f"| Avg Download/Doc | {s.avg_doc_download_time_s:.3f}s |",
            f"| Avg Upload/Doc | {s.avg_doc_upload_time_s:.3f}s |",
            f"| Median Download/Doc | {s.median_doc_download_time_s:.3f}s |",
            f"| p95 Download/Doc | {s.p95_doc_download_time_s:.3f}s |",
            f"| Avg Download Throughput | {s.avg_download_throughput_mbps:.2f} MB/s |",
            f"| Avg Upload Throughput | {s.avg_upload_throughput_mbps:.2f} MB/s |",
            "",
        ]

        # ── Storage providers ─────────────────────────────────────────
        lines += ["## ☁️ Storage Providers", ""]
        for provider, count in s.storage_providers.items():
            lines.append(f"- **{provider}:** {count} documents")
        lines.append("")

        # ── Top 10 largest ────────────────────────────────────────────
        lines += [
            "## 📦 Top 10 Largest Files",
            "",
            "| # | Doc ID | Size (MB) | Download (s) | Upload (s) | Query | S3 Path |",
            "|---|--------|-----------|--------------|------------|-------|---------|",
        ]
        for i, doc in enumerate(sorted(self.documents, key=lambda d: d.file_size_bytes, reverse=True)[:10], 1):
            mb = doc.file_size_bytes / 1_048_576
            lines.append(
                f"| {i} | `{doc.arxiv_id}` | {mb:.2f} | {doc.download_duration_s:.2f} "
                f"| {doc.upload_duration_s:.2f} | {doc.query[:22]} | `{doc.pdf_storage_path[:40]}` |"
            )
        lines.append("")

        # ── Unavailable ───────────────────────────────────────────────
        if self.unavailable:
            lines += [
                "## ⊘ Unavailable Documents (404 / Not Open Access)",
                "",
                "| Doc ID | Type | Reason | Query | Keyword | Timestamp |",
                "|--------|------|--------|-------|---------|-----------|",
            ]
            for u in self.unavailable:
                lines.append(
                    f"| `{u.arxiv_id}` | {u.pdf_type} | {u.reason} "
                    f"| {u.query[:20]} | {u.keyword_index} | {u.timestamp} |"
                )
            lines.append("")

        # ── Warnings ─────────────────────────────────────────────────
        if self.warnings:
            lines += [
                "## ⚠️ Warnings",
                "",
                "| Timestamp | Logger | Message |",
                "|-----------|--------|---------|",
            ]
            for w in self.warnings[:50]:
                lines.append(f"| {w.timestamp} | `{w.logger}` | {w.message[:80]} |")
            lines.append("")

        # ── Query breakdown ───────────────────────────────────────────
        lines += [
            "## 🔍 Keyword-Batch Breakdown",
            "",
            "| # | Query | Succeeded | New | Dups | NA | Bytes (MB) | Duration (s) | Results |",
            "|---|-------|-----------|-----|------|----|------------|--------------|---------|",
        ]
        for q in s.queries:
            lines.append(
                f"| {q['keyword_index']} | {q['query'][:28]} "
                f"| {q['succeeded']} | {q['new_documents']} | {q['duplicate_documents']} "
                f"| {q['not_available']} | {q['total_mb']} | {q['duration_s']} "
                f"| {q['total_results_found']:,} |"
            )
        lines.append("")

        return "\n".join(lines)


# ── Console printing ──────────────────────────────────────────────────────────

def print_statistics(
    stats: PipelineStatistics,
    run_config: Optional[GlobalRunConfig],
    global_summary: Optional[GlobalSummary],
    verbose: bool = False,
):
    W = 72
    print("\n" + "=" * W)
    print("  PIPELINE FETCH RESULTS — COMPREHENSIVE REPORT")
    print("=" * W)

    # ── Run config ────────────────────────────────────────────────────
    if run_config:
        print("\n⚙️  Run Configuration:")
        print(f"  Source            : {run_config.source}")
        print(f"  Target PDFs       : {run_config.target_pdfs}")
        print(f"  Per Keyword       : {run_config.per_keyword}")
        print(f"  Total Keywords    : {run_config.total_keywords}")
        print(f"  Delay             : {run_config.delay_s}s")
        print(f"  Dry Run           : {run_config.dry_run}")

    # ── Global summary ────────────────────────────────────────────────
    if global_summary:
        print("\n🏁 Global Summary:")
        print(f"  Total Unique PDFs : {global_summary.total_unique_pdfs}")
        print(f"  Unique Doc IDs    : {global_summary.unique_arxiv_ids}")
        print(f"  Keywords Exhausted: {global_summary.keywords_exhausted}")
        if global_summary.warning_message:
            print(f"  ⚠  {global_summary.warning_message}")

    # ── Counts ────────────────────────────────────────────────────────
    print("\n📊 Counts:")
    print(f"  Total Queries     : {stats.total_queries}")
    print(f"  Total Docs        : {stats.total_documents}")
    print(f"  Succeeded         : {stats.total_succeeded}")
    print(f"  New Unique        : {stats.total_new_unique}")
    print(f"  Duplicates        : {stats.total_duplicates}  ({stats.deduplication_rate} of succeeded)")
    print(f"  Not Available     : {stats.total_not_available}  (404 / not OA)")
    print(f"  Failed            : {stats.total_failed}")
    print(f"  Warnings          : {stats.total_warnings}")
    print(f"  Success Rate      : {stats.success_rate}")

    # ── Data volume ───────────────────────────────────────────────────
    print("\n💾 Data Volume:")
    print(f"  Total             : {stats.total_mb} MB  ({stats.total_bytes:,} bytes)")
    print(f"  Average Size      : {stats.avg_file_size_bytes:,.0f} bytes")
    print(f"  Median Size       : {stats.median_file_size_bytes:,.0f} bytes")
    print(f"  Min Size          : {stats.min_file_size_bytes:,} bytes")
    print(f"  Max Size          : {stats.max_file_size_bytes:,} bytes")

    # ── Timing ────────────────────────────────────────────────────────
    print("\n⏱️  Timing:")
    print(f"  Download Total    : {stats.total_download_time_s:.2f}s")
    print(f"  Upload Total      : {stats.total_upload_time_s:.2f}s")
    print(f"  Pipeline Total    : {stats.total_pipeline_time_s:.2f}s")
    print(f"  Avg Download/Doc  : {stats.avg_doc_download_time_s:.3f}s")
    print(f"  Avg Upload/Doc    : {stats.avg_doc_upload_time_s:.3f}s")
    print(f"  Median Download   : {stats.median_doc_download_time_s:.3f}s")
    print(f"  p95 Download      : {stats.p95_doc_download_time_s:.3f}s")

    # ── Throughput ────────────────────────────────────────────────────
    print("\n🚀 Throughput:")
    print(f"  Avg Download      : {stats.avg_download_throughput_mbps:.2f} MB/s")
    print(f"  Avg Upload        : {stats.avg_upload_throughput_mbps:.2f} MB/s")

    # ── Storage ───────────────────────────────────────────────────────
    print("\n☁️  Storage Providers:")
    for provider, count in stats.storage_providers.items():
        print(f"  {provider}: {count} documents")

    if verbose and stats.queries:
        print("\n🔍 Query Breakdown (top 20 by succeeded):")
        for q in sorted(stats.queries, key=lambda x: x["succeeded"], reverse=True)[:20]:
            dup_note = f"  ({q['duplicate_documents']} dups)" if q["duplicate_documents"] else ""
            print(
                f"  [{q['keyword_index']:>5}] '{q['query'][:30]}': "
                f"{q['new_documents']}/{q['succeeded']} new, "
                f"{round(q['total_mb'], 1)} MB, {q['duration_s']}s"
                f"{dup_note}"
            )

    print("\n" + "=" * W)


def print_unavailable(unavailable: list[UnavailableRecord]):
    if not unavailable:
        print("No unavailable documents found.")
        return
    print(f"\n⊘  Unavailable Documents ({len(unavailable)} total):")
    print("-" * 70)
    for u in unavailable:
        print(f"  {u.timestamp}  {u.arxiv_id:18} [{u.pdf_type}]  {u.reason}  [{u.keyword_index}] '{u.query}'")


def print_warnings(warnings: list[WarningRecord]):
    if not warnings:
        print("No warnings found.")
        return
    print(f"\n⚠️  Warnings ({len(warnings)} total):")
    print("-" * 70)
    for w in warnings:
        print(f"  {w.timestamp}  {w.logger}  {w.message}")


def print_by_keyword(query_stats: list[dict]):
    print(f"\n🔍 Per-Keyword Breakdown ({len(query_stats)} batches):")
    print("-" * 110)
    hdr = f"{'#':>6}  {'Query':<32}  {'Suc':>4}  {'New':>4}  {'Dup':>4}  {'NA':>3}  {'MB':>7}  {'s':>7}  {'Results':>8}"
    print(hdr)
    print("-" * 110)
    for q in query_stats:
        print(
            f"  {q['keyword_index']:>5}  {q['query'][:32]:<32}  {q['succeeded']:>4}  "
            f"{q['new_documents']:>4}  {q['duplicate_documents']:>4}  {q['not_available']:>3}  "
            f"{q['total_mb']:>7.2f}  {q['duration_s']:>7.1f}  {q['total_results_found']:>8,}"
        )


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="Parse pipeline.log and output comprehensive fetch results",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python utils/data_from_fetch.py                          # Full report
    python utils/data_from_fetch.py --stats                  # Statistics only
    python utils/data_from_fetch.py --export json            # Export to JSON
    python utils/data_from_fetch.py --export csv             # Export to CSV
    python utils/data_from_fetch.py --export markdown        # Markdown report
    python utils/data_from_fetch.py --query "cancer"         # Filter by query
    python utils/data_from_fetch.py --top 10                 # Top 10 largest
    python utils/data_from_fetch.py --unavailable            # Show 404 docs
    python utils/data_from_fetch.py --warnings               # Show warnings
    python utils/data_from_fetch.py --by-keyword             # Per-keyword table
    python utils/data_from_fetch.py --verbose                # All sections
        """,
    )
    ap.add_argument("--log", "-l", type=Path, default=DEFAULT_LOG_PATH,
                    help=f"Path to pipeline.log (default: {DEFAULT_LOG_PATH})")
    ap.add_argument("--source", choices=["biorxiv", "medrxiv", "clinical_trials", "pubmed"],
                    help="Filter to a specific source (also restricts manifest loading)")
    ap.add_argument("--manifests", type=Path,
                    default=PROJECT_ROOT / "temp" / "manifests",
                    help="Directory containing manifest JSON files (default: temp/manifests/)")
    ap.add_argument("--export", "-e", choices=["json", "csv", "markdown"], help="Export format")
    ap.add_argument("--output", "-o", help="Output file path (default: stdout)")
    ap.add_argument("--stats", "-s", action="store_true", help="Statistics summary only")
    ap.add_argument("--query", "-q", help="Filter documents by query term")
    ap.add_argument("--top", "-t", type=int, metavar="N", help="Top N largest documents")
    ap.add_argument("--unavailable", "-u", action="store_true", help="Show unavailable documents")
    ap.add_argument("--warnings", "-w", action="store_true", help="Show warnings")
    ap.add_argument("--by-keyword", action="store_true", help="Per-keyword breakdown table")
    ap.add_argument("--verbose", "-v", action="store_true", help="Verbose output with all sections")
    args = ap.parse_args()

    print(f"Parsing log file: {args.log}", file=sys.stderr)
    try:
        parser = LogParser(args.log)
        documents, unavailable, warnings, query_summaries, run_config, global_summary = parser.parse(
            manifest_dir=args.manifests,
            source_filter=args.source,
        )
        print(
            f"Found {len(documents)} documents, {len(unavailable)} unavailable, "
            f"{len(warnings)} warnings across {len(query_summaries)} keyword batches",
            file=sys.stderr,
        )
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error parsing log: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)

    analyzer = ResultsAnalyzer(documents, unavailable, warnings, query_summaries, run_config, global_summary)
    stats = analyzer.get_statistics()

    # ── Apply filters ──────────────────────────────────────────────────
    filtered_docs = documents
    if args.query:
        filtered_docs = analyzer.get_documents_by_query(args.query)
        print(f"Filtered to {len(filtered_docs)} documents matching '{args.query}'", file=sys.stderr)

    if args.top:
        filtered_docs = analyzer.get_top_largest(args.top)

    # ── Dispatch to output mode ────────────────────────────────────────
    if args.export:
        exporter = ResultExporter(filtered_docs, unavailable, warnings, stats)
        if args.export == "json":
            output_str = exporter.to_json()
        elif args.export == "csv":
            output_str = exporter.to_csv()
        else:
            output_str = exporter.to_markdown_report()

        if args.output:
            out_path = Path(args.output)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(output_str, encoding="utf-8")
            print(f"Exported to: {out_path}", file=sys.stderr)
        else:
            print(output_str)
        return

    if args.unavailable:
        print_unavailable(unavailable)
        return

    if args.warnings:
        print_warnings(warnings)
        return

    if args.by_keyword:
        print_by_keyword(stats.queries)
        return

    if args.stats:
        print_statistics(stats, run_config, global_summary, verbose=args.verbose)
        return

    if args.top:
        print(f"\nTop {args.top} Largest Files:")
        print("-" * 70)
        for i, doc in enumerate(filtered_docs, 1):
            mb = doc.file_size_bytes / 1_048_576
            print(f"{i:3}. {doc.arxiv_id:20} {mb:>8.2f} MB  dl:{doc.download_duration_s:.2f}s  ul:{doc.upload_duration_s:.2f}s  [{doc.query[:28]}]")
            print(f"       URL:      {doc.source_url}")
            print(f"       PDF:      {doc.pdf_storage_path}")
            print(f"       Meta:     {doc.metadata_storage_path}")
        return

    # Default: full report
    print_statistics(stats, run_config, global_summary, verbose=args.verbose)

    if args.verbose:
        if unavailable:
            print_unavailable(unavailable)
        if warnings:
            print_warnings(warnings)

    if filtered_docs:
        print("\n📋 Sample Documents (last 10):")
        print("-" * 70)
        for doc in filtered_docs[-10:]:
            size_kb = doc.file_size_bytes / 1024
            print(
                f"✓ {doc.arxiv_id:20} [{doc.pdf_type}] {size_kb:>9.1f} KB  "
                f"dl:{doc.download_duration_s:.2f}s  ul:{doc.upload_duration_s:.2f}s  "
                f"HTTP:{doc.http_status}"
            )
            print(f"  URL:  {doc.source_url}")
            print(f"  PDF:  {doc.pdf_storage_path}")
            print(f"  Meta: {doc.metadata_storage_path}")
            if doc.keyword_index:
                print(f"  [{doc.keyword_index}] '{doc.query}'")


if __name__ == "__main__":
    main()
