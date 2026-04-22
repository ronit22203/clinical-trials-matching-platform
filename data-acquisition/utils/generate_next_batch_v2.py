#!/usr/bin/env python3
"""
Second‑stage bulk fetcher for bioRxiv with a fresh keyword set.
Reads a file of already‑fetched IDs and appends new ones.
"""

import argparse
import json
import logging
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "fetch_pdfs.py"
MANIFEST_DIR = PROJECT_ROOT / "temp" / "manifests"
LOG_FILE = PROJECT_ROOT / "logs" / "pipeline.log"


def _setup_logging() -> logging.Logger:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("generate_next_batch_v2")
    logger.setLevel(logging.DEBUG)
    if not logger.handlers:
        fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(fh)
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(sh)
    return logger

# ===== NEW KEYWORDS – different from the first batch =====
# (These target areas like rare diseases, pediatrics, surgery, genomics, imaging, public health)
KEYWORDS = [
    # Rare & genetic diseases
    "cystic fibrosis",
    "sickle cell disease",
    "hemophilia",
    "huntington disease",
    "duchenne muscular dystrophy",
    "fragile x syndrome",
    "marfan syndrome",
    "turner syndrome",
    # Pediatrics
    "neonatal intensive care",
    "pediatric asthma",
    "childhood leukemia",
    "adolescent mental health",
    "pediatric vaccine",
    "kawasaki disease",
    # Surgery & interventions
    "minimally invasive surgery",
    "robotic surgery",
    "organ transplantation",
    "cardiac bypass",
    "orthopedic implant",
    "wound healing",
    "anesthesia safety",
    # Genomics & precision medicine
    "whole genome sequencing",
    "polygenic risk score",
    "pharmacogenomics",
    "gene therapy clinical trial",
    "epigenetics cancer",
    "single cell rna seq",
    "proteomics biomarker",
    # Medical imaging
    "deep learning radiology",
    "mri brain tumor",
    "ct lung nodule",
    "ultrasound fetal",
    "pet scan oncology",
    # Public health & epidemiology
    "disease outbreak modeling",
    "vaccine hesitancy",
    "health disparities",
    "maternal mortality",
    "telemedicine efficacy",
    "healthcare cost",
    "opioid epidemic",
    # Dentistry / ophthalmology / others
    "periodontal disease",
    "diabetic retinopathy",
    "glaucoma treatment",
    "cataract surgery",
    "hearing loss cochlear",
    "tinnitus",
    # Pharmacology / toxicology
    "adverse drug reaction",
    "drug repurposing",
    "nanoparticle drug delivery",
    "herbal medicine interaction",
    # Basic science with clinical angle
    "neurodegeneration mechanism",
    "autoimmunity pathogenesis",
    "tumor microenvironment",
    "angiogenesis inhibitor",
    "stem cell therapy",
]


def load_excluded_ids(exclude_file: Path) -> set[str]:
    if not exclude_file.exists():
        return set()
    with open(exclude_file) as f:
        return {line.strip() for line in f if line.strip()}


def append_ids(exclude_file: Path, new_ids: list[str]) -> None:
    if not new_ids:
        return
    with open(exclude_file, "a") as f:
        for pid in new_ids:
            f.write(pid + "\n")


def _run_fetch(keyword: str, max_pdfs: int, dry_run: bool, trace_id: str) -> dict:
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
    subprocess.run(cmd)  # streams output

    manifest_path = MANIFEST_DIR / f"{trace_id}.json"
    if dry_run or not manifest_path.exists():
        return {"succeeded": 0, "results": []}
    with open(manifest_path) as f:
        return json.load(f)


def main():
    log = _setup_logging()

    parser = argparse.ArgumentParser(description="Fetch another batch of bioRxiv PDFs (new keywords)")
    parser.add_argument("--target", type=int, default=500, help="Total new PDFs to fetch")
    parser.add_argument("--per-keyword", type=int, default=15, help="Max per keyword")
    parser.add_argument("--delay", type=float, default=3.0, help="Seconds between keywords")
    parser.add_argument("--exclude-file", type=Path,
                        default=PROJECT_ROOT / "temp" / "fetched_arxiv_ids.txt",
                        help="File with already fetched IDs (one per line)")
    parser.add_argument("--dry-run", action="store_true", help="Dry run only")
    args = parser.parse_args()

    exclude_file = args.exclude_file
    already_fetched = load_excluded_ids(exclude_file)
    log.info(f"Loaded {len(already_fetched)} existing IDs from {exclude_file}")

    target = args.target
    per_keyword = args.per_keyword
    delay = args.delay
    dry_run = args.dry_run

    total_new = 0
    run_at = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    new_ids_this_run = []

    log.info("=" * 60)
    log.info(f"  Next bioRxiv batch (v2 keywords) — target {target} new PDFs")
    log.info(f"  per_keyword={per_keyword}  delay={delay}s  dry_run={dry_run}")
    log.info("=" * 60)

    for i, keyword in enumerate(KEYWORDS, 1):
        if total_new >= target:
            break

        still_need = target - total_new
        fetch_n = min(per_keyword, still_need)

        trace_id = f"next-v2-{run_at}-{i:03d}"
        log.info(f"[{i:>3}/{len(KEYWORDS)}] '{keyword}' (need {still_need}, fetching up to {fetch_n})")

        manifest = _run_fetch(keyword, fetch_n, dry_run, trace_id)

        # Extract new IDs (adjust field name if needed – check your manifest!)
        batch_ids = []
        for r in manifest.get("results", []):
            if r.get("success"):
                pid = r.get("nct_id") or r.get("arxiv_id") or r.get("doi")
                if pid and pid not in already_fetched:
                    batch_ids.append(pid)
                    already_fetched.add(pid)

        new_count = len(batch_ids)
        total_new += new_count
        new_ids_this_run.extend(batch_ids)

        not_avail = manifest.get("not_available", 0)
        failed = manifest.get("failed", 0)

        log.info(
            f"         ✓ {new_count} new  |  ⊘ {not_avail} unavailable  "
            f"|  ✗ {failed} errors  |  total new so far: {total_new}"
        )

        if i < len(KEYWORDS) and total_new < target:
            time.sleep(delay)

    if not dry_run and new_ids_this_run:
        append_ids(exclude_file, new_ids_this_run)
        log.info(f"Appended {len(new_ids_this_run)} new IDs to {exclude_file}")

    log.info("=" * 60)
    log.info("  Finished.")
    log.info(f"  New unique PDFs fetched: {total_new}")
    log.info(f"  Total known IDs now     : {len(already_fetched)}")
    log.info("=" * 60)

    if total_new < target:
        log.warning(f"Only reached {total_new}/{target}. Add more keywords or increase --per-keyword.")
        sys.exit(1)


if __name__ == "__main__":
    main()
