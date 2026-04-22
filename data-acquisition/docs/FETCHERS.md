# Fetcher Architecture

> Source-specific fetcher implementations for ClinicalTrials.gov, PubMed, bioRxiv, and medRxiv.

---

## Overview

All fetchers inherit from `BaseFetcher` (`src/fetchers/base.py`). The abstract interface is intentionally minimal — every source-specific detail (API endpoint, rate limit, PDF URL pattern, identifier scheme) lives in the corresponding YAML config under `config/data-acquisition/sources/`.

```
BaseFetcher (ABC)
├── search(query, max_results) → list[SearchRecord]
├── fetch_pdf(record_id, pdf_type) → Optional[FetchResult]
├── generate_metadata(record, pdf_type) → dict
└── cleanup()                                   # removes tracked temp files
```

The orchestrator (`scripts/fetch_pdfs.py`) uses `inspect.iscoroutinefunction()` to detect whether `search()` is async and routes execution accordingly. Fetchers that perform HTTP calls should implement `search()` as `async`.

---

## Source Reference

| Source | Fetcher class | Config file | Identifier | `search()` style |
|--------|---------------|-------------|------------|-----------------|
| ClinicalTrials.gov | `ClinicalTrialsFetcher` | `clinicaltrials.yml` | NCT ID | async |
| bioRxiv | `BioRxivFetcher` | `biorxiv.yml` | arXiv short ID | sync |
| medRxiv | `MedRxivFetcher` | `medrxiv.yml` | DOI (`/` → `_` in storage keys) | async |
| PubMed | `PubMedFetcher` | `pubmed.yaml` | PMID | async |

---

## Config Structure

Every source config follows the same top-level schema:

```yaml
api:
  base_url: https://...
  search_endpoint: /api/query
  timeout_seconds: 30
  max_retries: 3
  user_agent: "multi-cloud-graphrag/1.0"
  # source-specific pdf_patterns, endpoint keys, etc.

rate_limit:
  calls_per_minute: 30
  concurrency: 5
  burst_size: 10

search:
  default_query: "clinical trial"
  max_results_per_query: 100
  max_pdfs_per_run: 500

storage:
  primary:
    prefix: raw/{source}/
  fallback:
    prefix: raw/{source}/

metadata:
  include_fields: [title, authors, date, abstract]
  custom_fields: {}
  version: "1.0"
```

All values are consumed by the fetcher at runtime. No API endpoints, rate limits, or storage prefixes are hardcoded in Python.

---

## bioRxiv vs. medRxiv Differences

Although they share a similar config structure, the two preprint fetchers differ in search strategy and identifier scheme:

| Aspect | bioRxiv | medRxiv |
|--------|---------|---------|
| Search API | arXiv library (keyword query) | medRxiv REST API date-range scan |
| Search approach | Keyword query → filter by server | Scan date window → client-side keyword filter |
| Identifier | arXiv short ID | DOI (`10.1101/YYYY.MM.DD.XXXXXX`) |
| PDF URL | `arxiv.org/pdf/{id}` | `medrxiv.org/content/{doi}.full.pdf` |
| Authors field | List from arXiv API | Semicolon-separated string from medRxiv API |
| Storage key | `raw/biorxiv/{arxiv_id}/paper.pdf` | `raw/medrxiv/{doi_underscored}/paper.pdf` |

`MedRxivFetcher` does not depend on the `arxiv` library — it uses `httpx` exclusively (already a dependency of `BioRxivFetcher`).

---

## CLI Usage

Each fetcher module exposes a CLI for development and debugging:

```bash
# Validate a source config
python src/fetchers/clinical_trials_pdf.py \
    --config config/data-acquisition/sources/clinicaltrials.yml validate

# Search for records
python src/fetchers/clinical_trials_pdf.py \
    --config config/data-acquisition/sources/clinicaltrials.yml search "diabetes"

# Fetch a specific PDF
python src/fetchers/clinical_trials_pdf.py \
    --config config/data-acquisition/sources/clinicaltrials.yml fetch NCT12345678 protocol
```

The same pattern applies to all fetchers (`biorxiv.py`, `medrxiv.py`, `pubmed.py`).

---

## Adding a New Source

1. **Create a config** at `config/data-acquisition/sources/{name}.yml` following the schema above.
2. **Register** the config path and fetcher class in `scripts/fetch_pdfs.py` (the `_SOURCES` and `_FETCHERS` dicts).
3. **Implement a fetcher** class inheriting `BaseFetcher`:

```python
from src.fetchers.base import BaseFetcher, SearchRecord, FetchResult
from pathlib import Path

class MySourceFetcher(BaseFetcher):
    async def search(self, query: str, max_results: int) -> list[SearchRecord]:
        # Call your source API, return SearchRecord objects
        ...

    async def fetch_pdf(self, record_id: str, pdf_type: str = "full") -> FetchResult | None:
        # Download PDF bytes, return FetchResult
        ...

    def generate_metadata(self, record: SearchRecord, pdf_type: str) -> dict:
        # Return a dict; this becomes the .metadata.json sidecar
        ...
```

Rate limiting, storage failover, manifest writing, and metrics are handled automatically by the orchestrator — the fetcher only needs to implement the three methods above.

---

## Data Types

```python
@dataclass
class SearchRecord:
    id: str              # source-specific identifier (NCT ID, arXiv ID, DOI, PMID)
    title: str
    abstract: str
    authors: list[str]
    published_date: str  # ISO 8601
    source: str          # "clinicaltrials" | "biorxiv" | "medrxiv" | "pubmed"
    metadata: dict       # source-specific additional fields

@dataclass
class FetchResult:
    record_id: str
    pdf_type: str        # e.g. "protocol", "results", "full"
    pdf_bytes: bytes
    metadata: dict
    storage_key: str     # final key used in the storage provider
    fallback_chain: list[str]  # providers attempted, in order
```

