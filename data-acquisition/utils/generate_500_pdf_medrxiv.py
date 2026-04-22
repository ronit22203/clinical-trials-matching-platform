#!/usr/bin/env python3
"""
Bulk-fetch ~500 health-sciences PDFs from medRxiv across clinical keyword categories.

Iterates through keywords, calls fetch_pdfs.py for each, reads the resulting
manifest to count *actual* successes, deduplicates by DOI, and stops when
TARGET is reached. Already-fetched DOIs are persisted to a file so re-runs
skip duplicates.

Usage:
    python utils/generate_500_pdf_medrxiv.py
    python utils/generate_500_pdf_medrxiv.py --target 100 --per-keyword 20 --dry-run
    python utils/generate_500_pdf_medrxiv.py --exclude-file temp/fetched_medrxiv_dois.txt
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

# Medical keyword categories for medRxiv.
# medRxiv focuses on *clinical* and *population* health sciences — distinct from
# bioRxiv's basic life-science scope.  Keywords are ordered broad-to-specific so
# early passes yield high hit rates before falling back to narrow terms.
KEYWORDS = [
    # Clinical trials & therapeutics
    "randomized controlled trial",
    "clinical trial intervention",
    "placebo controlled trial",
    "drug efficacy safety",
    "treatment outcome",
    # COVID-19 & infectious disease
    "COVID-19 clinical outcome",
    "SARS-CoV-2 infection",
    "long COVID post-acute",
    "influenza vaccination efficacy",
    "pneumonia antibiotic treatment",
    "tuberculosis drug resistant",
    "HIV viral suppression",
    "malaria prevention treatment",
    "dengue hemorrhagic fever",
    "hepatitis B C antiviral",
    # Cardiology
    "myocardial infarction outcome",
    "atrial fibrillation stroke",
    "heart failure mortality",
    "hypertension blood pressure",
    "coronary artery disease",
    # Oncology & cancer screening
    "breast cancer screening mammography",
    "lung cancer early detection",
    "colorectal cancer colonoscopy",
    "cervical cancer HPV vaccine",
    "prostate cancer PSA",
    "pancreatic cancer prognosis",
    "cancer chemotherapy toxicity",
    "immunotherapy checkpoint inhibitor",
    # Neurology & mental health
    "stroke thrombolysis outcome",
    "alzheimer dementia cognitive",
    "parkinson levodopa treatment",
    "epilepsy seizure control",
    "depression antidepressant trial",
    "anxiety cognitive behavioral therapy",
    "schizophrenia antipsychotic",
    "suicide prevention mental health",
    "burnout healthcare worker",
    # Endocrinology & metabolism
    "type 2 diabetes glycemic control",
    "insulin resistance obesity",
    "thyroid disease treatment",
    "metabolic syndrome prevention",
    # Respiratory
    "asthma inhaler treatment",
    "COPD pulmonary rehabilitation",
    "sleep apnea CPAP",
    "interstitial lung disease",
    # Gastroenterology
    "inflammatory bowel disease",
    "crohn colitis biologic",
    "liver cirrhosis hepatitis",
    "irritable bowel syndrome",
    # Musculoskeletal
    "rheumatoid arthritis biologic",
    "osteoporosis fracture prevention",
    "knee osteoarthritis replacement",
    "back pain treatment",
    # Pediatrics
    "pediatric vaccination schedule",
    "childhood obesity intervention",
    "neonatal mortality preterm",
    "pediatric asthma management",
    "childhood leukemia chemotherapy",
    # Women's & reproductive health
    "maternal mortality obstetric",
    "preeclampsia gestational hypertension",
    "preterm birth prevention",
    "infertility IVF outcome",
    "breast cancer hormonal therapy",
    # Epidemiology & public health
    "vaccine hesitancy coverage",
    "health disparities socioeconomic",
    "opioid overdose addiction",
    "tobacco smoking cessation",
    "alcohol use disorder",
    "physical activity cardiovascular",
    "diet nutrition chronic disease",
    "telemedicine remote monitoring",
    "healthcare-associated infection",
    # Diagnostics & imaging
    "AI deep learning diagnosis",
    "biomarker prediction outcome",
    "MRI neuroimaging clinical",
    "point of care testing",
    "liquid biopsy cancer detection",
    # Surgery & intensive care
    "surgical site infection prevention",
    "ICU mechanical ventilation outcome",
    "sepsis management mortality",
    "organ transplant rejection",
    "minimally invasive laparoscopic",
    # Genetics & precision medicine
    "pharmacogenomics drug response",
    "polygenic risk score disease",
    "gene therapy rare disease",
    "CRISPR clinical application",
    "whole exome sequencing diagnosis",
]


def _setup_logging() -> logging.Logger:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("generate_500_pdf_medrxiv")
    logger.setLevel(logging.DEBUG)
    if not logger.handlers:
        fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(fh)
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(sh)
    return logger


def load_excluded_ids(exclude_file: Path) -> set[str]:
    if not exclude_file.exists():
        return set()
    with open(exclude_file) as f:
        return {line.strip() for line in f if line.strip()}


def append_ids(exclude_file: Path, new_ids: list[str]) -> None:
    if not new_ids:
        return
    exclude_file.parent.mkdir(parents=True, exist_ok=True)
    with open(exclude_file, "a") as f:
        for doi in new_ids:
            f.write(doi + "\n")


def _run_fetch(keyword: str, max_pdfs: int, dry_run: bool, trace_id: str) -> dict:
    """Run fetch_pdfs.py for medRxiv, streaming output to terminal."""
    cmd = [
        sys.executable,
        str(SCRIPT_PATH),
        "--source", "medrxiv",
        "--query", keyword,
        "--max-pdfs", str(max_pdfs),
        "--trace-id", trace_id,
    ]
    if dry_run:
        cmd.append("--dry-run")

    result = subprocess.run(cmd)  # streams stdout/stderr to terminal

    if result.returncode not in (0, 1):  # exit 1 = partial failures, still ok
        print(f"  [error] subprocess failed (rc={result.returncode})")
        return {"succeeded": 0, "results": []}

    manifest_path = MANIFEST_DIR / f"{trace_id}.json"
    if dry_run or not manifest_path.exists():
        return {"succeeded": 0, "results": []}

    with open(manifest_path) as f:
        return json.load(f)


def main() -> None:
    log = _setup_logging()

    parser = argparse.ArgumentParser(description="Bulk-fetch ~500 medRxiv health-science PDFs")
    parser.add_argument("--target", type=int, default=500, help="Total PDFs to fetch (default: 500)")
    parser.add_argument("--per-keyword", type=int, default=15, help="Max PDFs per keyword (default: 15)")
    parser.add_argument("--delay", type=float, default=3.0, help="Seconds between keyword runs (default: 3)")
    parser.add_argument(
        "--exclude-file", type=Path,
        default=PROJECT_ROOT / "temp" / "fetched_medrxiv_dois.txt",
        help="File with already-fetched DOIs, one per line",
    )
    parser.add_argument("--dry-run", action="store_true", help="Pass --dry-run to fetcher (no downloads)")
    args = parser.parse_args()

    target: int = args.target
    per_keyword: int = args.per_keyword
    delay: float = args.delay
    dry_run: bool = args.dry_run
    exclude_file: Path = args.exclude_file

    already_fetched = load_excluded_ids(exclude_file)
    log.info(f"Loaded {len(already_fetched)} existing DOIs from {exclude_file}")

    total_new = 0
    new_ids_this_run: list[str] = []
    run_at = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    log.info("=" * 60)
    log.info(f"  medRxiv bulk fetch — target {target} PDFs")
    log.info(f"  per_keyword={per_keyword}  delay={delay}s  dry_run={dry_run}")
    log.info("=" * 60)

    for i, keyword in enumerate(KEYWORDS, 1):
        if total_new >= target:
            break

        still_need = target - total_new
        fetch_n = min(per_keyword, still_need)

        trace_id = f"medrxiv-bulk-{run_at}-{i:03d}"
        log.info(f"[{i:>3}/{len(KEYWORDS)}] '{keyword}' (need {still_need}, fetching up to {fetch_n})")

        manifest = _run_fetch(keyword, fetch_n, dry_run, trace_id)

        # medRxiv uses DOI as the primary identifier
        batch_ids: list[str] = []
        for r in manifest.get("results", []):
            if r.get("success"):
                doi = r.get("nct_id") or r.get("doi")
                if doi and doi not in already_fetched:
                    batch_ids.append(doi)
                    already_fetched.add(doi)

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
        log.info(f"Appended {len(new_ids_this_run)} new DOIs to {exclude_file}")

    log.info("=" * 60)
    log.info("  Finished.")
    log.info(f"  New unique PDFs fetched : {total_new}")
    log.info(f"  Total known DOIs now    : {len(already_fetched)}")
    log.info(f"  Keywords exhausted      : {total_new < target}")
    log.info("=" * 60)

    if total_new < target:
        log.warning(f"⚠ Only reached {total_new}/{target}. Add more keywords or increase --per-keyword.")
        sys.exit(1)


if __name__ == "__main__":
    main()
