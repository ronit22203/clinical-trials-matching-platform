"""
fetch_pdfs.py — Main orchestrator for the multi-cloud PDF ingestion pipeline.

Loads all configuration exclusively from:
  config/app.yaml

Credentials come from .env (loaded at startup):
  AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY  (or AWS_PROFILE for named profile)
  AZURE_STORAGE_CONNECTION_STRING

Usage:
    python scripts/fetch_pdfs.py --source clinical_trials --query "cancer immunotherapy" --max-pdfs 5
    python scripts/fetch_pdfs.py --source clinical_trials --query "diabetes" --max-pdfs 1 --dry-run
    python scripts/fetch_pdfs.py --source clinical_trials --query "alzheimer" --max-pdfs 20 --trace-id run-001
"""

import argparse
import asyncio
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ── Load .env before anything else ──────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """Load .env and .env.local into os.environ (no external dependency required).

    Precedence: .env.local > .env (both relative to data-acquisition root).
    Also checks the monorepo root (one level up) for .env.local.
    Shell environment always wins — existing vars are never overwritten.
    """
    import os
    _repo_root = _ROOT.parent  # healthcare-platform/

    for env_path in [
        _ROOT / ".env",
        _repo_root / ".env.local",  # root-level shared config
        _ROOT / ".env.local",       # module-level override (highest priority)
    ]:
        if not env_path.exists():
            continue
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                if k not in os.environ:  # don't overwrite shell env
                    os.environ[k] = v.strip()


_load_dotenv()

import os  # noqa: E402
sys.path.insert(0, str(_ROOT))

from src.config_loader import load_acquisition_config, load_source_config  # noqa: E402
from src.fetchers.biorxiv import BioRxivFetcher  # noqa: E402
from src.fetchers.clinical_trials_pdf import ClinicalTrialsFetcher  # noqa: E402
from src.fetchers.medrxiv import MedRxivFetcher  # noqa: E402
from src.fetchers.pubmed import PubMedFetcher  # noqa: E402
from src.storage import MultiCloudStorageManager  # noqa: E402

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO")),
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("fetch_pdfs")

# ── Config loader ────────────────────────────────────────────────────────────
_FETCHERS = {
    "biorxiv": BioRxivFetcher,
    "clinical_trials": ClinicalTrialsFetcher,
    "medrxiv": MedRxivFetcher,
    "pubmed": PubMedFetcher,
}


def _load_all_configs(source: str, storage_mode: str = "local") -> tuple[dict, dict | None, dict | None, dict]:
    """Return (source_cfg, aws_cfg, azure_cfg, local_cfg).

    In local mode, aws_cfg and azure_cfg are None — cloud YAML files are not read.
    """
    acquisition_cfg = load_acquisition_config()
    source_cfg = load_source_config(source)
    storage_cfg = acquisition_cfg["storage"]
    local_cfg = storage_cfg["local_fallback"]

    # Resolve base_dir to absolute anchored at _ROOT (data-acquisition/).
    # This makes the path correct regardless of the cwd at invocation time.
    raw_base = local_cfg["paths"]["base_dir"]
    if not Path(raw_base).is_absolute():
        local_cfg["paths"]["base_dir"] = str((_ROOT / raw_base).resolve())

    if storage_mode == "local":
        return source_cfg, None, None, local_cfg

    return (
        source_cfg,
        storage_cfg["aws_s3"],
        storage_cfg["azure_blob"],
        local_cfg,
    )


# ── Manifest ──────────────────────────────────────────────────────────────────

def _save_manifest(trace_id: str, results: list[dict], query: str, source: str) -> Path:
    manifest_dir = _ROOT / "temp" / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / f"{trace_id}.json"
    manifest = {
        "trace_id": trace_id,
        "source": source,
        "query": query,
        "run_at": datetime.now(timezone.utc).isoformat(),
        "total": len(results),
        "succeeded": sum(1 for r in results if r.get("success")),
        "not_available": sum(1 for r in results if r.get("not_available")),
        "failed": sum(1 for r in results if not r.get("success") and not r.get("not_available")),
        "results": results,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return manifest_path


# ── Core async pipeline ───────────────────────────────────────────────────────

async def run(
    source: str,
    query: str,
    max_pdfs: int,
    dry_run: bool,
    trace_id: str,
    pdf_types: list[str],
    storage_mode: str = "local",
) -> list[dict]:
    source_cfg, aws_cfg, azure_cfg, local_cfg = _load_all_configs(source, storage_mode)

    fetcher = _FETCHERS[source](source_cfg)

    storage = None
    if not dry_run:
        if storage_mode == "local":
            storage = MultiCloudStorageManager.local_only(local_cfg)
        else:
            providers_cfg = load_acquisition_config()["storage"]["providers"]
            storage = MultiCloudStorageManager.from_configs(
                providers_cfg, aws_cfg, azure_cfg, local_cfg
            )

    # ── Search ────────────────────────────────────────────────────────────────
    logger.info(f"Searching [{source}] for: '{query}' (max {max_pdfs} PDFs)")
    # search() is sync on BioRxivFetcher, async on ClinicalTrialsFetcher/PubMedFetcher
    import inspect
    if inspect.iscoroutinefunction(fetcher.search):
        records = await fetcher.search(query, max_results=max_pdfs)
    else:
        records = fetcher.search(query, max_results=max_pdfs)

    if not records:
        logger.warning("No studies found.")
        await fetcher.close()
        return []

    logger.info(f"Found {len(records)} studies")
    if dry_run:
        logger.info("DRY RUN — no downloads or uploads will occur")

    # ── Fetch + store ─────────────────────────────────────────────────────────
    results: list[dict] = []
    pdf_count = 0
    temp_dir = _ROOT / "temp" / "downloads"
    temp_dir.mkdir(parents=True, exist_ok=True)

    for record in records:
        if pdf_count >= max_pdfs:
            break

        for pdf_type in pdf_types:
            if pdf_count >= max_pdfs:
                break

            nct_id = record.nct_id

            # Dry-run: just report the URL that would be fetched
            if dry_run:
                # Build a best-effort preview URL without downloading
                api_cfg = source_cfg.get("api", {})
                if "pdf_patterns" in api_cfg:
                    # ClinicalTrials / PubMed style
                    pattern = api_cfg["pdf_patterns"].get(pdf_type, "")
                    last_two = nct_id[-2:] if len(nct_id) >= 2 else nct_id
                    url = pattern.format(nct_id=nct_id, last_two=last_two)
                elif "pdf_url_pattern" in api_cfg:
                    # bioRxiv uses {arxiv_id}, medRxiv uses {doi}
                    if source == "medrxiv":
                        url = api_cfg["pdf_url_pattern"].format(doi=nct_id)
                    else:
                        url = api_cfg["pdf_url_pattern"].format(arxiv_id=nct_id)
                else:
                    url = f"<unknown URL pattern for {source}>"
                logger.info(f"  [DRY RUN] {nct_id} [{pdf_type}]  {url}")
                results.append({
                    "nct_id": nct_id, "pdf_type": pdf_type,
                    "title": record.brief_title, "success": True,
                    "dry_run": True, "url": url,
                })
                pdf_count += 1
                continue

            # Real fetch
            today = datetime.now(timezone.utc).strftime("%Y/%m/%d")
            prefix = source_cfg.get("storage", {}).get("primary", {}).get("prefix", f"raw/{source}/")
            storage_key = f"{prefix}{today}/{nct_id}/{pdf_type}.pdf"

            # Skip if already stored (idempotent re-runs)
            if storage and await storage.exists(storage_key):
                logger.info(f"  ⊘ {nct_id} [{pdf_type}] already stored, skipping")
                results.append({
                    "nct_id": nct_id, "pdf_type": pdf_type,
                    "success": True, "skipped": True, "storage_path": storage_key,
                })
                pdf_count += 1
                continue

            t0 = time.monotonic()
            fetch_result = await fetcher.fetch_pdf(nct_id, pdf_type, temp_dir)
            fetch_s = round(time.monotonic() - t0, 2)

            if not fetch_result or not fetch_result.success:
                error = fetch_result.error if fetch_result else "Unknown"
                is_unavailable = "404" in error or "Not Open Access" in error
                if is_unavailable:
                    reason = "not Open Access" if "Not Open Access" in error else "404"
                    logger.info(f"  ⊘ {nct_id} [{pdf_type}] not available ({reason}) — skipping")
                    results.append({
                        "nct_id": nct_id, "pdf_type": pdf_type,
                        "success": False, "stage": "fetch",
                        "error": error, "not_available": True,
                    })
                else:
                    logger.warning(f"  ✗ {nct_id} [{pdf_type}] fetch failed: {error}")
                    results.append({
                        "nct_id": nct_id, "pdf_type": pdf_type,
                        "success": False, "stage": "fetch", "error": error,
                    })
                pdf_count += 1
                continue

            logger.info(
                f"  ↓ {nct_id} [{pdf_type}]  "
                f"{fetch_result.file_size_bytes:,} bytes  ({fetch_s}s)"
            )

            metadata = fetcher.generate_metadata(record, pdf_type, fetch_result)
            metadata["trace_id"] = trace_id

            t1 = time.monotonic()
            store_result = await storage.store(
                file_path=fetch_result.pdf_path,
                key=storage_key,
                metadata=metadata,
                content_type="application/pdf",
            )
            store_s = round(time.monotonic() - t1, 2)

            if store_result.success:
                meta_key = storage_key.replace(".pdf", ".json")
                await storage.store_metadata(meta_key, metadata)

                fallback_note = (
                    f"  [via {' → '.join(store_result.fallback_chain)}]"
                    if store_result.fallback_chain else ""
                )
                logger.info(
                    f"  ✓ {nct_id} [{pdf_type}] → {store_result.provider}"
                    f"  ({store_s}s){fallback_note}"
                )
                results.append({
                    "nct_id": nct_id, "pdf_type": pdf_type,
                    "title": record.brief_title, "success": True,
                    "storage_provider": store_result.provider,
                    "storage_path": store_result.path,
                    "fallback_chain": store_result.fallback_chain,
                    "file_size_bytes": fetch_result.file_size_bytes,
                    "fetch_seconds": fetch_s, "store_seconds": store_s,
                })
            else:
                logger.error(f"  ✗ {nct_id} [{pdf_type}] store failed: {store_result.error}")
                results.append({
                    "nct_id": nct_id, "pdf_type": pdf_type,
                    "success": False, "stage": "store",
                    "error": store_result.error,
                    "fallback_chain": store_result.fallback_chain,
                })

            fetcher.cleanup()
            pdf_count += 1

    if storage:
        await storage.close()
    await fetcher.close()
    return results


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Multi-cloud PDF ingestion pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--source", choices=list(_FETCHERS), default="clinical_trials")
    parser.add_argument("--query", type=str, default=None,
                        help="Search query (defaults to source config default_query)")
    parser.add_argument("--max-pdfs", type=int, default=5)
    parser.add_argument("--pdf-types", nargs="+",
                        choices=["protocol", "results", "fulltext", "paper"],
                        default=None,
                        help="PDF types to fetch (default: protocol for clinical_trials, fulltext for pubmed, paper for biorxiv)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print URLs without downloading or uploading")
    parser.add_argument("--storage-mode", choices=["local", "cloud"], default="local",
                        help="Storage mode: local (default, no cloud credentials needed) or cloud (uses providers.yml chain)")
    parser.add_argument("--trace-id", type=str, default=None)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    trace_id = args.trace_id or f"run-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"

    # Default pdf_types per source if not specified
    if args.pdf_types is None:
        if args.source == "pubmed":
            args.pdf_types = ["fulltext"]
        elif args.source in ("biorxiv", "medrxiv"):
            args.pdf_types = ["paper"]
        else:
            args.pdf_types = ["protocol"]

    if args.query is None:
        source_cfg = load_source_config(args.source)
        args.query = source_cfg.get("search", {}).get("default_query", "clinical trials")

    logger.info(
        "\n" + "=" * 55 + "\n"
        f"  trace_id     : {trace_id}\n"
        f"  source       : {args.source}\n"
        f"  query        : {args.query}\n"
        f"  max_pdfs     : {args.max_pdfs}\n"
        f"  pdf_types    : {args.pdf_types}\n"
        f"  storage_mode : {args.storage_mode}\n"
        f"  dry_run      : {args.dry_run}\n"
        + "=" * 55
    )

    t_start = time.monotonic()
    results = asyncio.run(run(
        source=args.source, query=args.query, max_pdfs=args.max_pdfs,
        dry_run=args.dry_run, trace_id=trace_id, pdf_types=args.pdf_types,
        storage_mode=args.storage_mode,
    ))
    elapsed = round(time.monotonic() - t_start, 1)

    succeeded = sum(1 for r in results if r.get("success"))
    not_available = sum(1 for r in results if r.get("not_available"))
    failed = len(results) - succeeded - not_available

    logger.info(
        "\n" + "=" * 55 + "\n"
        f"  Done in       : {elapsed}s\n"
        f"  Succeeded     : {succeeded}\n"
        f"  Not available : {not_available}  (404 or not Open Access)\n"
        f"  Failed        : {failed}  (real errors)\n"
        f"  Total         : {len(results)}\n"
        + "=" * 55
    )

    if not args.dry_run and results:
        manifest_path = _save_manifest(trace_id, results, args.query, args.source)
        logger.info(f"  Manifest  : {manifest_path.relative_to(_ROOT)}")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
