#!/usr/bin/env python3
"""
Bulk-fetch ~500 medical PDFs from bioRxiv across medical keyword categories.

Iterates through keywords, calls fetch_pdfs.py for each, reads the resulting
manifest to count *actual* successes, deduplicates by arxiv_id, and stops
when TARGET is reached.

Usage:
    python utils/generate_500_pdfs.py
    python utils/generate_500_pdfs.py --target 100 --per-keyword 20 --dry-run
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "fetch_pdfs.py"
MANIFEST_DIR = PROJECT_ROOT / "temp" / "manifests"

# Medical keyword categories — ordered broad-to-specific so early passes
# yield high hit rates before falling back to narrow terms.
KEYWORDS = [
    # Broad disease areas
    "cancer immunotherapy",
    "diabetes mellitus",
    "COVID-19 treatment",
    "alzheimer disease",
    "parkinson disease",
    "stroke neurological",
    "heart failure cardiac",
    "hypertension cardiovascular",
    "obesity metabolic",
    "asthma respiratory",
    # Infectious disease
    "pneumonia infection",
    "tuberculosis pulmonary",
    "malaria parasite",
    "HIV antiretroviral",
    "hepatitis liver",
    "influenza viral",
    "dengue fever",
    "sepsis inflammation",
    # Oncology subtypes
    "breast cancer treatment",
    "lung cancer therapy",
    "prostate cancer",
    "colorectal cancer",
    "pancreatic cancer",
    "glioblastoma brain tumor",
    "leukemia hematology",
    "lymphoma blood cancer",
    "melanoma skin cancer",
    "ovarian cancer",
    # Neurology / psychiatry
    "epilepsy seizure",
    "multiple sclerosis",
    "depression antidepressant",
    "anxiety disorder",
    "schizophrenia psychosis",
    "autism spectrum",
    "ADHD neurodevelopmental",
    # Genetics / genomics
    "CRISPR gene editing",
    "genome sequencing variant",
    "hereditary mutation",
    "sickle cell anemia",
    "cystic fibrosis",
    "muscular dystrophy",
    # Immunology / inflammation
    "autoimmune rheumatoid",
    "vaccine immunization",
    "cytokine storm",
    "T cell therapy",
    "antibody therapeutic",
    # Diagnostics / imaging
    "biomarker diagnostic",
    "MRI imaging",
    "liquid biopsy",
    "proteomics plasma",
    # Pharmacology
    "drug resistance antibiotic",
    "clinical trial pharmacology",
    "drug delivery nanoparticle",
    "precision medicine",
]


def _run_fetch(keyword: str, max_pdfs: int, dry_run: bool, trace_id: str) -> dict:
    """Run fetch_pdfs.py, streaming output to terminal, and return manifest data."""
    cmd = [
        sys.executable,
        str(SCRIPT_PATH),
        "--source", "biorxiv",
        "--query", keyword,
        "--max-pdfs", str(max_pdfs),
        "--trace-id", trace_id,
    ]
    if dry_run:
        cmd.append("--dry-run")

    result = subprocess.run(cmd)  # streams stdout/stderr to terminal

    if result.returncode not in (0, 1):  # exit 1 = some failures, still ok
        print(f"  [error] subprocess failed (rc={result.returncode})")
        return {"succeeded": 0, "results": []}

    # Manifests are only written on real (non-dry) runs
    manifest_path = MANIFEST_DIR / f"{trace_id}.json"
    if dry_run or not manifest_path.exists():
        return {"succeeded": 0, "results": []}

    with open(manifest_path) as f:
        return json.load(f)


def main() -> None:
    parser = argparse.ArgumentParser(description="Bulk-fetch ~500 bioRxiv medical PDFs")
    parser.add_argument("--target", type=int, default=500, help="Total PDFs to fetch (default: 500)")
    parser.add_argument("--per-keyword", type=int, default=15, help="Max PDFs per keyword (default: 15)")
    parser.add_argument("--delay", type=float, default=3.0, help="Seconds between keyword runs (default: 3)")
    parser.add_argument("--dry-run", action="store_true", help="Pass --dry-run to fetcher (no downloads)")
    args = parser.parse_args()

    target: int = args.target
    per_keyword: int = args.per_keyword
    delay: float = args.delay
    dry_run: bool = args.dry_run

    seen_ids: set[str] = set()       # deduplicate across keyword runs
    total_succeeded = 0
    run_at = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    print(f"\n{'='*60}")
    print(f"  bioRxiv bulk fetch — target {target} PDFs")
    print(f"  per_keyword={per_keyword}  delay={delay}s  dry_run={dry_run}")
    print(f"{'='*60}\n")

    for i, keyword in enumerate(KEYWORDS, 1):
        if total_succeeded >= target:
            break

        still_need = target - total_succeeded
        fetch_n = min(per_keyword, still_need)

        trace_id = f"bulk-{run_at}-{i:03d}"
        print(f"[{i:>3}/{len(KEYWORDS)}] '{keyword}'  (need {still_need}, fetching up to {fetch_n})")

        manifest = _run_fetch(keyword, fetch_n, dry_run, trace_id)

        # Count new unique successes
        new_ids = [
            r["nct_id"] for r in manifest.get("results", [])
            if r.get("success") and r.get("nct_id") not in seen_ids
        ]
        seen_ids.update(new_ids)
        batch_count = len(new_ids)
        total_succeeded += batch_count

        not_avail = manifest.get("not_available", 0)
        failed = manifest.get("failed", 0)

        print(
            f"         ✓ {batch_count} new  |  ⊘ {not_avail} unavailable  "
            f"|  ✗ {failed} errors  |  total so far: {total_succeeded}"
        )

        if i < len(KEYWORDS) and total_succeeded < target:
            time.sleep(delay)

    print(f"\n{'='*60}")
    print(f"  Finished.")
    print(f"  Total unique PDFs fetched : {total_succeeded}")
    print(f"  Unique arxiv IDs          : {len(seen_ids)}")
    print(f"  Keywords exhausted        : {total_succeeded < target}")
    print(f"{'='*60}\n")

    if total_succeeded < target:
        print(f"⚠ Only reached {total_succeeded}/{target}. Add more keywords or increase --per-keyword.")
        sys.exit(1)


if __name__ == "__main__":
    main()
