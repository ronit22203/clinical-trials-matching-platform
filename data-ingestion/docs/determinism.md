# Determinism & Reproducibility

This document explains the determinism tracking system, which proves that the medical data ingestion pipeline produces identical outputs for identical inputs.

## Overview

The pipeline captures a complete **execution fingerprint** after each stage, including:
- Full environment metadata (OS, Python version, pip freeze hash)
- Model and tool versions (Surya, Spacy, Presidio, etc.)
- Hardware configuration (CPU count, GPU/MPS availability)
- Hyperparameters and configuration (batch sizes, device settings, etc.)
- Git commit SHA

This ensures **determinism is a contract, not a hope**. By capturing full environment context, you can detect drift from:
- Dependency version mismatches
- LLM stochasticity or randomness
- Race conditions in parallel processing
- Hardware inconsistencies

## Architecture

### UUIDs & Document Tracking

**Document UUID** (parent): Permanent ID for each PDF file
- Generated deterministically from filename: `SHA256(filename)` → UUID
- Same filename always produces the same UUID
- Reused across all pipeline runs of that document

**Execution UUID** (child): Unique ID for each pipeline run
- Randomly generated per execution
- Tracks "run N" of a document
- Enables comparison: "How did run 1 vs run 2 differ?"

### Storage: Hybrid Approach

**SQLite Database** (`data/determinism.db`):
- Stores structured metadata and small output snapshots
- 3 tables: documents, executions, stage_records

**Content-Addressable Storage** (`data/artifacts/`):
- Stores large binaries (PDFs, images, embeddings)
- Directory structure: `data/artifacts/{stage}/{hash_prefix}/{full_hash}.{ext}`
- References stored in database
- Idempotent: same hash = same file (no duplicates)

## Usage

### Running the Pipeline with Tracking

```bash
make run
# Or with specific skip:
make run SKIP=vectorize
```

The pipeline now automatically:
1. Generates Document UUID from PDF filename
2. Generates Execution UUID for this run
3. Creates database records for documents and executions
4. Records each stage with full fingerprint and hashes
5. Stores intermediate outputs for inspection

### Verifying Determinism (Comparing Two Runs)

After running the pipeline twice on the same PDF:

```bash
# List all tracked documents
make list-documents

# Output:
# TRACKED DOCUMENTS:
# Document ID                              Filename
# ────────────────────────────────────────────────────
# 056c935e-4dfa-223c-bf08-27a8ff2b43fc   report.pdf

# List all executions of a document
make list-executions DOC=056c935e-4dfa-223c-bf08-27a8ff2b43fc

# Output:
# EXECUTIONS FOR DOCUMENT: 056c935e-4dfa-223c-bf08-27a8ff2b43fc
# ────────────────────────────────────────────────────────────────────────────
# Execution ID                             Timestamp                 Status
# ────────────────────────────────────────────────────────────────────────────
# abc-uuid-1                               2026-02-15T16:30:00       completed
# abc-uuid-2                               2026-02-15T16:35:00       completed

# Compare two executions
make compare-runs \
  DOC=056c935e-4dfa-223c-bf08-27a8ff2b43fc \
  EXEC1=abc-uuid-1 \
  EXEC2=abc-uuid-2
```

### Advanced: Detect Version Mismatches

```bash
python scripts/compare_executions.py \
  --doc 056c935e-4dfa-223c-bf08-27a8ff2b43fc \
  --exec1 abc-uuid-1 \
  --exec2 abc-uuid-2 \
  --version-check
```

### Stage-Specific Diffs

```bash
python scripts/compare_executions.py \
  --doc 056c935e-4dfa-223c-bf08-27a8ff2b43fc \
  --exec1 abc-uuid-1 \
  --exec2 abc-uuid-2 \
  --stage-diff convert
```

## Best Practices

1. **Run twice**: After any code/dependency change, run the pipeline twice and verify determinism.
2. **Pin dependencies**: Use `pip freeze > requirements.txt` to ensure reproducibility.
3. **Check versions**: Use `--version-check` flag to detect dependency mismatches.
4. **Version lock**: Commit git SHA for full traceability.
5. **Document drift**: If determinism check fails, investigate and log the cause.

## Troubleshooting

### "No stages matched (0/5)"
- Check if both executions completed: `make list-executions DOC=<uuid>`
- Verify execution status in database

### "Different hashes but same input"
- Environment mismatch detected
- Check fingerprint diff: `--version-check` flag
- Common causes: Python version, library versions, hardware differences

### Large artifacts aren't stored
- Large binaries (PDFs, images) are stored in `data/artifacts/`
- Database stores only path references
