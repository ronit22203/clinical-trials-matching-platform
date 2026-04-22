Copilot Instructions for Medical Data Ingestion Pipeline
Makefile topology: use the single repo-root Makefile. The module-local Makefile is gone; use root `make ingestion-*` targets.
Project Overview
A production-grade, modular medical PDF ingestion pipeline with full traceability across 5 distinct stages. Each stage outputs intermediate files to a dedicated data/ subdirectory for inspection and debugging.

Core Architecture:

Stage 1 (Extract): PDF → OCR JSON via Surya OCR + debug PNGs
Stage 2 (Convert): OCR JSON → Markdown via SuryaToMarkdown
Stage 3 (Clean): Markdown → Cleaned Markdown via TextCleaner (with PII redaction)
Stage 4 (Chunk): Cleaned Markdown → JSON chunks via MarkdownChunker (context-aware hierarchical)
Stage 5 (Vectorize): Chunks → Vector embeddings in Qdrant via MedicalVectorizer
All intermediate outputs are persisted for debugging and validation.

Build, Test, and Run Commands
Installation
make ingestion-install          # Install dependencies from requirements.txt
Testing
make ingestion-test                  # Run all ingestion tests
make ingestion-test-processors       # Test TextCleaner & MarkdownChunker on markdown files
make ingestion-test-embedder         # Test embedder (clean → chunk → embed → qdrant)
make ingestion-test-qdrant           # Test Qdrant connection & collection management
Running the Pipeline
make ingestion-run               # Run all 5 stages end-to-end
make ingestion-run SKIP=ocr      # Skip a specific stage (ocr, convert, clean, chunk, vectorize)
make ingestion-inspect           # Inspect outputs from all stages
Docker & Storage Management
make ingestion-qdrant-up         # Start Qdrant
make ingestion-qdrant-down       # Stop Qdrant
make ingestion-qdrant-clear      # Clear embeddings collection
make ingestion-qdrant-delete     # Delete collection
make ingestion-neo4j-build       # Build knowledge graph from chunks
make ingestion-neo4j-delete      # Delete all graph data
make ingestion-neo4j-stats       # Show graph statistics
Determinism & Reproducibility
make ingestion-compare-runs DOC=<uuid> EXEC1=<uuid> EXEC2=<uuid>  # Compare two executions
make ingestion-list-documents    # List all tracked documents with UUIDs
make ingestion-list-executions DOC=<uuid>                         # List executions for a document
Cleanup
make ingestion-clean             # Remove __pycache__, .pyc files, logs
make ingestion-clean-all         # Reset all pipeline outputs (data/ocr, data/markdown, etc.)
High-Level Architecture
Module Structure
src/
├── extractors/       # PDF extraction & conversion to Markdown
│   ├── pdf_marker_v2.py     # Surya OCR orchestration (Stage 1)
│   ├── surya_converter.py   # OCR JSON → Markdown conversion (Stage 2)
│   └── base.py              # Abstract base for all extractors
├── processors/       # Data cleaning & chunking
│   ├── cleaner.py          # Markdown cleaning + PII redaction (Stage 3)
│   └── chunker.py          # Context-aware hierarchical chunking (Stage 4)
├── storage/          # Embedding & vector DB management
│   ├── embedder.py         # MedicalVectorizer (Stage 5)
│   └── qdrant_manager.py   # Qdrant client wrapper
└── retrieval/        # RAG retrieval
    └── hybrid.py            # Hybrid search (semantic + keyword)
Data Flow
Input: data/raw/*.pdf files
Stage 1 Output: data/ocr/*_ocr.json + debug PNGs
Stage 2 Output: data/markdown/*_converted.md
Stage 3 Output: data/cleaned/*_cleaned.md
Stage 4 Output: data/chunks/*_chunks.json (hierarchical structure with parent/child relationships)
Stage 5 Output: Vectors indexed in Qdrant (and Neo4j for knowledge graph)
Configuration
Primary config: ../config/app.yaml (all stage parameters: device, batch sizes, PII settings, chunking strategy)
Docker Compose: infra/docker-compose.yaml (Qdrant + Neo4j services with persistent volumes)
Key Innovation: Context-Aware Hierarchical Chunking
The MarkdownChunker preserves document structure by:

Detecting headers, sections, and list items from markdown format
Creating parent-child relationships between chunks
Storing hierarchical metadata in JSON (depth, parent_id, section_title, etc.)
This enables RAG systems to understand semantic context, not just isolated chunks
Key Conventions & Patterns
BaseExtractor Pattern (Stage 1-2)
All extractors inherit from BaseExtractor and implement:

def extract(self, file_path: Path, **kwargs) -> Dict[str, Any]:
    """Returns standardized dict with 'content' and 'metadata' keys"""
Strictly enforces: Input Path → Output Dict contract
See src/extractors/base.py for the abstract class
Configuration Loading Pattern
from src.storage.embedder import ConfigLoader
config = ConfigLoader.load_config(config_path)
All stage parameters are YAML-driven from ../config/app.yaml
Device selection (mps for Apple Silicon, cpu fallback) is configured centrally
Logging & Traceability
PipelineLogger class in scripts/run_pipeline.py manages all logging
All stages log to logs/ingestion.log with timestamps
Each stage logs: start time, file count, success/failure, output path
PII Redaction (Stage 3 - TextCleaner)
Uses Presidio analyzer/anonymizer (default behavior: remove_pii=True)
Custom recognizers for Singaporean medical data:
Singapore NRIC/FIN: [STFG]\d{7}[A-Z]
MCR Number (Medical Registration): \d{6}
Can be disabled by passing remove_pii=False to TextCleaner()
Chunking Strategy (Stage 4 - MarkdownChunker)
Hierarchical structure: Detects headers and creates parent-child relationships
Max chunk size: Configurable via ../config/app.yaml (chunking → max_chunk_size)
Overlap: Chunks overlap by a configurable token count for context continuity
Metadata fields: parent_id, depth, section_title, original_position preserved in JSON
Test Data Location
Test OCR JSON: tests/test_data/Sample-filled-in-MR_ocr.json
Tests create intermediate output in tests/ subdirectories (not committed)
No pytest/unittest
Tests are standalone scripts (tests/test_*.py), not pytest-based
Run with: python tests/test_processors.py (not pytest)
This allows flexible test flow: setup → execute → inspect outputs
Determinism & Reproducibility
Every pipeline run captures a complete execution fingerprint (environment, versions, hardware, hyperparameters). This enables provable reproducibility:

Same input + Same environment = Same output ✓
Detects drift from dependency versions, randomness, race conditions
Full audit trail in SQLite database (data/determinism.db)
First-class CLI tooling to compare executions: make ingestion-compare-runs
See docs/determinism.md for detailed usage.

When Making Changes
Modifying a stage: Ensure you understand the input/output contract. Check ../config/app.yaml for that stage's parameters.
Adding a new processor: Inherit from BaseExtractor if it's an input extractor, or follow the pattern in TextCleaner/MarkdownChunker.
Testing changes: Use make ingestion-test-<stage> to validate before running full pipeline.
Debugging: Use make ingestion-inspect to view all intermediate outputs; they're persisted for analysis.
Qdrant/Neo4j changes: Ensure Docker is running (make ingestion-qdrant-up) before testing storage components.
Configuration changes: Update ../config/app.yaml and re-run pipeline; no code changes needed for tuning.
Verifying reproducibility: After changes, run pipeline twice and use make ingestion-compare-runs to verify determinism.
