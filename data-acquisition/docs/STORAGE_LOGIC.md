# Storage Architecture

> For cloud provider setup, see [SETTING_UP_CLOUD_DATABASES.md](SETTING_UP_CLOUD_DATABASES.md).  
> For design rationale, see [DESIGN.md](../DESIGN.md).

---

## Provider Chain

Storage operations follow a strict priority order with automatic failover and per-provider retry:

```
Primary   → AWS S3       (ap-south-1, S3 Express One Zone)
Fallback1 → Azure Blob   (centralindia, Standard_LRS)
Fallback2 → Local disk   (base_dir from config/data-acquisition/storage/local_fallback.yml)
```

Every `StorageResult` carries a `fallback_chain` field recording which providers were attempted for that operation, in order. This is used for monitoring and cost attribution.

---

## Configuration Files

| File | Purpose |
|------|---------|
| `config/data-acquisition/storage/providers.yml` | Provider chain order, failover triggers, `max_consecutive_failures`, routing keys |
| `config/data-acquisition/storage/aws_s3.yml` | S3 bucket name, region, prefix, retry settings |
| `config/data-acquisition/storage/azure_blob.yml` | Azure container name, account, prefix, retry settings |
| `config/data-acquisition/storage/local_fallback.yml` | Local base directory, path templates, retention policy, disk usage alerts |

`MultiCloudStorageManager.from_configs()` reads `providers.yml` → routing keys → looks up the correct bucket/container name in the provider-specific YAML. No bucket or container names are hardcoded in Python.

`${ENV_VAR}` patterns in any storage YAML are resolved at runtime via `os.path.expandvars`.

---

## Key Behaviours

- **Metadata sidecars**: every PDF is stored alongside a `.metadata.json` file at `{key}.metadata.json`. This sidecar contains the full metadata dict from `generate_metadata()`.
- **Retry with exponential backoff**: each provider retries independently using `max_attempts` and `backoff_factor` from its YAML config, with optional jitter.
- **Failover on error types**: `providers.yml` defines which error types trigger failover (e.g. `UploadError`, `TimeoutError`, `StorageUnavailableError`). Successful writes to a lower-priority provider are recorded but do not suppress the fallback entry in `fallback_chain`.
- **Consecutive failure threshold**: after `max_consecutive_failures` errors on a provider, it is marked degraded and skipped for subsequent operations until the next health check.
- **Local cleanup**: `LocalStorageProvider.cleanup_expired()` deletes files older than `retention_days`. Controlled by `cleanup.enabled` in `local_fallback.yml`.
- **Disk usage monitoring**: `LocalStorageProvider.get_disk_usage()` returns utilisation metrics. Alerts at the `alert_at_percent` threshold defined in config.

---

## Storage Key Layout

All providers use the same path structure:

```
{prefix}/{source}/{year}/{month}/{day}/{paper_id}/
    paper.pdf
    paper.metadata.json
```

**Source-specific prefixes:**

| Source | S3 prefix | Azure prefix |
|--------|-----------|--------------|
| ClinicalTrials | `raw/clinical_trials/` | `raw/clinical_trials/` |
| bioRxiv | `raw/biorxiv/` | `raw/biorxiv/` |
| medRxiv | `raw/medrxiv/` | `raw/medrxiv/` |
| PubMed | `raw/pubmed/` | `raw/pubmed/` |

**medRxiv note:** DOI slashes (`/`) are replaced with underscores in storage keys to avoid path ambiguity. A DOI of `10.1101/2024.01.15.123456` becomes the directory `10.1101_2024.01.15.123456`.

---

## Example Directory Structure

```
raw/
├── biorxiv/
│   └── 2026/03/03/
│       └── {arxiv_id}/
│           ├── paper.pdf
│           └── paper.metadata.json
└── medrxiv/
    └── 2026/03/04/
        └── 10.1101_2026.03.04.XXXXXX/
            ├── paper.pdf
            └── paper.metadata.json
```

---

## Observed File Size Distribution

Based on 2,072 documents ingested during the initial batch run:

| Metric | Value |
|--------|-------|
| Smallest | 10.1 KiB |
| Largest | 108.1 MiB |
| Median | ~1.6 MiB |
| Total corpus size | 4.4 GiB |

The pipeline handles the full range from small abstract-only PDFs to large genomic supplement documents without special-casing.

---

## StorageResult Schema

```python
@dataclass
class StorageResult:
    success: bool
    provider: str          # provider that successfully stored the file
    key: str               # final storage key (may differ from requested key on fallback)
    fallback_chain: list[str]  # all providers attempted, in order
    error: Optional[str]   # last error message if any provider failed
    bytes_written: int
    duration_seconds: float
```

