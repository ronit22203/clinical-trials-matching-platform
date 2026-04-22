# Medical Data Ingestion Pipeline

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11.14](https://img.shields.io/badge/python-3.11.14-blue)](https://www.python.org/downloads/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Tests Passing](https://img.shields.io/badge/tests-passing-brightgreen)]()
[![contributions welcome](https://img.shields.io/badge/contributions-welcome-brightgreen.svg)](CONTRIBUTING.md)

**MARA** (Medical Archival and Retrieval Augmentation) is a production-grade, modular pipeline for ingesting medical PDFs with **full traceability and context-awareness**.

> **Makefile topology changed:** run all `make` commands from the **repo root**. Use `make ingestion-*` targets such as `make ingestion-install`, `make ingestion-qdrant-up`, and `make ingestion-run`.

## Key Features

✨ **5-Stage Processing Pipeline**
- **Stage 1**: PDF → OCR JSON (Surya OCR + debug visualizations)
- **Stage 2**: OCR JSON → Markdown (SuryaToMarkdown converter)
- **Stage 3**: Markdown → Cleaned (TextCleaner)
- **Stage 4**: Cleaned → Chunks with context (MarkdownChunker)
- **Stage 5**: Chunks → Vector DB (MedicalVectorizer → Qdrant)

🔍 **Full Traceability** - All intermediate outputs are saved and inspectable for debugging
📊 **Context-Aware Chunking** - Preserves document structure for RAG systems
🏥 **Medical-Optimized** - Handles complex medical documents and terminology
🚀 **Production-Ready** - Docker support, Azure integration, comprehensive logging
☁️ **Azure Integration** - Terraform infrastructure-as-code and SDK utilities

Outputs saved to:
- **data/ocr/** - OCR JSON + debug visualizations
- **data/markdown/** - Raw markdown conversion
- **data/cleaned/** - Cleaned and normalized markdown
- **data/chunks/** - Context-aware chunks with metadata

## Overview

This pipeline implements a sophisticated five-stage architecture with context-aware chunking:

1. **OCR Extraction** - Convert PDFs to JSON using Surya (with debug visualizations)
2. **Format Conversion** - Transform OCR JSON to readable Markdown
3. **Cleaning** - Remove artifacts and normalize content
4. **Chunking** - Split into context-aware chunks with hierarchical metadata
5. **Vectorization** - Generate embeddings and index in Qdrant

The key innovation is **context-aware hierarchical chunking** that preserves document structure, ensuring RAG systems understand semantic context.

## Quick Start

### Prerequisites

- **Python** 3.10+
- **Docker** (for Qdrant)
- **Git LFS** (for large files): `brew install git-lfs` (macOS) or see [git-lfs.com](https://git-lfs.com)
- **4GB+ RAM** (for embeddings model)
- **Apple Silicon**: MPS GPU support (or use `--device cpu`)

### Setup

```bash
# Clone repository
git clone https://github.com/yourusername/prod_mara_ingestion.git
cd prod_mara_ingestion

# Initialize git LFS
git lfs install
git lfs pull

# Install dependencies
make ingestion-install

# Start Qdrant vector database
make ingestion-qdrant-up
```

### Run Full Pipeline

```bash
# 1. Place PDFs in data/raw/
cp your_medical_report.pdf data/raw/

# 2. Run complete 5-stage pipeline
make ingestion-run

# 3. Inspect outputs at each stage
make ingestion-inspect

# 4. Stop Qdrant when done
make ingestion-qdrant-down
```

Outputs are saved to:
- **Stage 1**: `data/ocr/` (JSON + debug PNGs)
- **Stage 2**: `data/markdown/` (raw markdown)
- **Stage 3**: `data/cleaned/` (cleaned markdown)
- **Stage 4**: `data/chunks/` (chunks JSON)
- **Stage 5**: Qdrant database

## Project Structure

```
prod_mara_ingestion/
├── README.md                    # This file
├── Makefile                     # Build and task automation
├── requirements.txt             # Python dependencies
│
├── config/
│
│
├── src/                         # Core package
│   ├── extractors/
│   │   ├── base.py              # Abstract extractor interface
│   │   ├── pdf_marker_v2.py     # Surya OCR pipeline
│   │   └── surya_converter.py   # OCR JSON → Markdown converter
│   ├── processors/
│   │   ├── cleaner.py           # Markdown text cleaning
│   │   └── chunker.py           # Context-aware chunking
│   └── storage/
│       ├── qdrant_client.py     # Qdrant collection management
│       └── embedder.py          # Embedding and indexing
│
├── scripts/                     # Entry points (CLI)
│   ├── run_pipeline.py          # 5-stage orchestrator
│   └── inspect_pipeline.py      # Pipeline inspection tool
│
├── tests/                       # Test suite
│   ├── test_processors.py       # Test cleaner and chunker
│   ├── test_embedder.py         # Test vectorization
│   ├── test_qdrant.py           # Test Qdrant connection
│   └── test_pdf_marker.py       # Test PDF extraction
│
├── docs/                        # Detailed documentation
│   ├── data_flow.md             # Complete data flow & traceability guide
│   ├── extractor.md             # OCR extraction details
│   ├── processor.md             # Cleaning and chunking
│   └── storage.md               # Vectorization and Qdrant
│
├── infra/
│   └── docker-compose.yaml      # Qdrant container setup
│
├── data/                        # Local data storage (gitignored)
│   ├── raw/                     # Input: Original PDF files
│   ├── ocr/                     # Output: OCR JSONs + debug images
│   ├── markdown/                # Output: Raw markdown
│   ├── cleaned/                 # Output: Cleaned markdown
│   └── chunks/                  # Output: Chunked JSON with metadata
│
└── logs/                        # Pipeline logs
    └── ingestion.log            # Complete execution log
```

## Configuration

All configuration is centralized in the repo-root [../config/app.yaml](../config/app.yaml) under the `data_ingestion` section:

```yaml
project_root: "."
input_dir: "data/raw"
log_file: "logs/ingestion.log"

pdf_to_markdown:
  batch_size: 10
  verbose: true

preprocessing:
  remove_page_markers: true
  normalize_headings: true
  fix_hyphenation: true

vectorization:
  qdrant_url: "http://localhost:6333"
  collection_name: "medical_papers"
  model_name: "BAAI/bge-small-en-v1.5"
  chunk_size: 1500
  chunk_overlap: 300
  batch_size: 64
```

## Usage Guide

### Full Pipeline (All 5 Stages)

```bash
# Run complete pipeline
make ingestion-run
```

This will:
1. **Stage 1**: Convert PDFs → OCR JSON (with debug visualizations)
2. **Stage 2**: Convert OCR JSON → Markdown
3. **Stage 3**: Clean → normalized Markdown
4. **Stage 4**: Chunk → JSON with context metadata
5. **Stage 5**: Vectorize → Index in Qdrant

Outputs saved to `data/stage{1-4}_*/` with full traceability.

### Inspect Pipeline Outputs

```bash
make ingestion-inspect
```

Displays:
- ✓ File counts at each stage
- File sizes and reduction percentages
- Sample content from each stage
- Chunk statistics
- Qdrant collection status

### Skip Specific Stages

```bash
# Skip OCR (assume _ocr.json already exists)
make ingestion-run SKIP=ocr

# Skip conversion
make ingestion-run SKIP=convert

# Skip cleaning
make ingestion-run SKIP=clean

# Skip chunking
make ingestion-run SKIP=chunk

# Skip vectorization
make ingestion-run SKIP=vectorize
```

### Custom Configuration

```bash
# Use custom config file
python scripts/run_pipeline.py --config /path/to/config.yaml

# Override input directory
python scripts/run_pipeline.py --input-dir /path/to/pdfs
```

### 1. OCR Extraction (Stage 1)

**Input**: PDFs in `data/raw/`  
**Output**: `data/ocr/{filename}_ocr.json` + debug images  
**Time**: ~20-30 sec per 50-page PDF

```bash
# Pipeline automatically runs Stage 1
# Or skip if you have existing OCR JSON:
make ingestion-run SKIP=ocr
```

**Outputs**:
- `{filename}_ocr.json`: Surya OCR results with text lines, bboxes, confidence
- `{filename}/debug_visualizations/`: PNG files with OCR bounding boxes
  - Green boxes = high confidence (≥ 0.80)
  - Red boxes = low confidence (< 0.80)

**Example**:
```json
{
  "page_number": 1,
  "text_lines": [
    {
      "text": "MEDICAL REPORT",
      "confidence": 0.95,
      "bbox": [50, 50, 200, 75]
    }
  ]
}
```

### 2. Markdown Conversion (Stage 2)

**Input**: `{filename}_ocr.json`  
**Output**: `data/markdown/{filename}_converted.md`  
**Time**: <1 sec

Converts OCR JSON to readable Markdown:
- Infers headers from bold text & layout geometry
- Preserves spatial structure (paragraphs, gaps)
- No cleaning applied (raw conversion)

**Example**:
```markdown
# MEDICAL REPORT

## Patient Demographics

Name: John Doe
DOB: 01/15/1980

## Clinical Findings

The patient presents with...
```

### 3. Markdown Cleaning (Stage 3)

**Input**: `{filename}_converted.md`  
**Output**: `data/cleaned/{filename}_cleaned.md`  
**Time**: <1 sec

Cleans and normalizes Markdown:
- Removes phantom image links: `![...](...)` → removed
- Removes phantom citation links: `[]()` → removed
- Linearizes markdown tables for RAG
- Fixes hyphenation: `treat-ment` → `treatment`
- Collapses excessive whitespace

**Size reduction**: Typically 85-95% of original retained

### 4. Markdown Chunking (Stage 4)

**Input**: `{filename}_cleaned.md`  
**Output**: `data/chunks/{filename}_chunks.json`  
**Time**: <1 sec

Creates context-aware chunks:

```python
from src.processors.chunker import MarkdownChunker

chunker = MarkdownChunker(max_tokens=1500)
chunks = chunker.chunk(markdown_text)

# Output: List of dicts
# {
#   'content': 'Context: Clinical Studies > Efficacy\n\nThe drug showed...',
#   'context': 'Clinical Studies > Efficacy',
#   'level': 2
# }
```

**Features**:
- **Context-aware**: Each chunk includes breadcrumb path
- **Header-respecting**: Never splits headers or atomic blocks
- **Size-bounded**: Each chunk ≤ max_tokens (configurable)
- **Overlapping**: Adjacent chunks share sentences for continuity

**Example JSON**:
```json
{
  "filename": "medical_report",
  "total_chunks": 42,
  "chunks": [
    {
      "content": "Context: Section 1 > Subsection\n\nText content here...",
      "context": "Section 1 > Subsection",
      "level": 2
    }
  ]
}
```

### 5. Vectorization & Indexing (Stage 5)

**Input**: Chunks from Stage 4  
**Output**: Indexed vectors in Qdrant  
**Time**: ~100-500 vectors/sec

Generates embeddings and indexes for semantic search:

```bash
# Automatically run by 'make ingestion-run'
# Or manually:
python scripts/run_pipeline.py --skip-vectorize=false

# Query the database:
from qdrant_client import QdrantClient
client = QdrantClient("http://localhost:6333")
results = client.search(collection_name="medical_papers", ...)
```

**Embedding Model**: `BAAI/bge-small-en-v1.5` (384 dimensions)  
**Metadata stored**: source, context, level, chunk_index


## API Reference

### TextCleaner

```python
from src.processors.cleaner import TextCleaner

cleaner = TextCleaner()
cleaned = cleaner.clean(text)
```

Performs:
- Removes phantom citation links: `[]()` -> removed
- Linearizes markdown tables for RAG
- Merges hyphenated words split across lines
- Collapses excessive whitespace

See [docs/processor.md](docs/processor.md) for details.

### MarkdownChunker

```python
from src.processors.chunker import MarkdownChunker

chunker = MarkdownChunker(max_tokens=512)
chunks = chunker.chunk(text)

# Output: List of dicts
# {
#   'content': 'Context: Clinical Studies > Efficacy Results\n\nThe drug showed...',
#   'context': 'Clinical Studies > Efficacy Results',
#   'level': 2
# }
```

Implements context-aware hierarchical chunking:
- Respects document structure (headers, lists, code blocks)
- Prepends full breadcrumb context to each chunk
- Never splits atomic blocks (lists, code)
- Preserves semantic coherence

See [docs/processor.md](docs/processor.md) for details.

### MedicalVectorizer

```python
from src.storage.embedder import MedicalVectorizer

vectorizer = MedicalVectorizer()
vectorizer.run("data/interim")  # Process directory
```

Pipeline:
1. Clean markdown with TextCleaner
2. Chunk with MarkdownChunker
3. Generate embeddings (SentenceTransformer)
4. Upsert to Qdrant with metadata

See [docs/storage.md](docs/storage.md) for details.

### QdrantManager

```python
from src.storage.qdrant_client import QdrantManager

manager = QdrantManager()
manager.list_collections()
manager.get_collection_stats()
manager.clear_collection()  # Delete all points
manager.delete_collection()  # Delete collection
```

Or via CLI:

```bash
python src/storage/qdrant_client.py list
python src/storage/qdrant_client.py stats
python src/storage/qdrant_client.py clear
python src/storage/qdrant_client.py delete
```

See [docs/storage.md](docs/storage.md) for details.

## Make Commands

### Testing

```bash
make ingestion-test                # Run all tests
make ingestion-test-processors     # Test cleaner & chunker
make ingestion-test-embedder       # Test full vectorization
make ingestion-test-qdrant         # Test Qdrant connection
```

### Pipeline Execution

```bash
make ingestion-run                 # Full 5-stage pipeline (all outputs saved)
make ingestion-inspect             # Inspect outputs at all stages
make ingestion-run SKIP=ocr        # Skip OCR (assume _ocr.json exists)
make ingestion-run SKIP=convert    # Skip conversion
make ingestion-run SKIP=clean      # Skip cleaning
make ingestion-run SKIP=chunk      # Skip chunking
make ingestion-run SKIP=vectorize  # Skip vectorization
```

### Docker/Qdrant

```bash
make ingestion-qdrant-up      # Start Qdrant
make ingestion-qdrant-down    # Stop Qdrant
make ingestion-qdrant-logs    # View logs
make ingestion-qdrant-clear   # Clear embeddings
make ingestion-qdrant-delete  # Delete collection
```

### Maintenance

```bash
make ingestion-clean        # Remove cache and logs
make ingestion-clean-all    # Reset all data
make ingestion-install      # Install dependencies
```

## Architecture

### Three-Stage Pipeline

```
Input (PDF)
    |
    v
[STAGE 1: EXTRACTION]
    - Convert to Markdown
    - Extract text, tables, images
    - Output: Markdown files in data/interim/
    |
    v
[STAGE 2: PROCESSING]
    - Clean Markdown (remove noise)
    - Chunk hierarchically (respect structure)
    - Preserve context breadcrumbs
    - Output: Context-aware chunks
    |
    v
[STAGE 3: VECTORIZATION]
    - Generate embeddings
    - Index in Qdrant
    - Store metadata (source, context, level)
    - Output: Searchable vector database
```

### Key Design Decisions

**Context-Aware Chunking**: Unlike naive token-based splitting, our chunker respects document structure. Each chunk includes its full hierarchical context:

```
Context: Introduction > Background > Related Work
Content: Smith et al. (2020) demonstrated...
```

**Metadata Preservation**: Qdrant stores:
- `source`: Original document name
- `context`: Full breadcrumb path
- `level`: Header level (H1, H2, H3)
- `chunk_index`: Position in document

This enables retrieval that understands semantic context.

**Atomic Block Protection**: Lists, code blocks, and other atomic elements are never split mid-block, preserving integrity.

## Performance

Typical benchmarks (BAAI/bge-small-en-v1.5):

- **Extraction**: 10-20 sec per PDF (depends on size)
- **Cleaning**: <1 sec per 1000 chars
- **Chunking**: <1 sec per document
- **Embedding**: 100-500 vectors/sec (batch size dependent)

For a 50-page medical paper:
- Extraction: 20 seconds
- Processing: 2 seconds
- Vectorization: 30 seconds
- **Total: ~50 seconds**

## Troubleshooting

### Qdrant Connection Error

```bash
# Ensure Qdrant is running
make ingestion-qdrant-up

# Verify connection
make ingestion-test-qdrant
```

### No Markdown Files Found

```bash
# Place PDFs in data/raw/
ls data/raw/

# Extract to markdown
make extract

# Verify output
ls data/interim/
```

### Out of Memory

Reduce batch size in settings.yaml:

```yaml
vectorization:
  batch_size: 32  # From 64
```

Or reduce model size:

```yaml
model_name: "BAAI/bge-small-zh-v1.5"  # Smaller model
```

### Slow Embedding Generation

Use GPU acceleration:

```bash
pip install torch-cuda  # NVIDIA GPUs
pip install torch-mps   # Apple Silicon
```

Model will auto-detect and use GPU if available.

## Dependencies

See [requirements.txt](requirements.txt) for full list:

- `marker-pdf`: PDF to Markdown extraction
- `qdrant-client`: Vector database client
- `sentence-transformers`: Embedding generation
- `pyyaml`: Configuration parsing

## Documentation

Detailed documentation for each component:

- [docs/extractor.md](docs/extractor.md) - PDF extraction details
- [docs/processor.md](docs/processor.md) - Cleaning and chunking
- [docs/storage.md](docs/storage.md) - Vectorization and Qdrant

## Contributing

This is a production pipeline. Modifications should:
1. Pass all tests: `make ingestion-test`
2. Update relevant docs
3. Include test coverage for new features

## License

MIT - Medical Data Ingestion Pipeline

---

## Cloud Deployment

### Azure

Deploy to Azure using provided Terraform configuration:

```bash
cd infra/azure
terraform init
terraform plan
terraform apply
```

See [infra/azure/README.md](infra/azure/README.md) for detailed Azure deployment instructions.

**Azure Resources Provisioned:**
- Storage Account (blob containers for PDFs and data)
- Container Registry (for Docker images)
- App Service (to run the pipeline)
- Cognitive Services (optional OCR enhancement)

### Docker

Build and run using Docker:

```bash
docker build -t mara-pipeline:latest .
docker run -v $(pwd)/data:/app/data mara-pipeline:latest make ingestion-run
```

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

### Quick Contribution Steps

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Make changes and add tests
4. Run tests: `make ingestion-test`
5. Commit with conventional messages: `git commit -m "feat: description"`
6. Push and open a pull request

### Development

```bash
# Install dev dependencies
pip install -r requirements-dev.txt

# Run tests with coverage
pytest --cov=src tests/

# Format code
black src/

# Check type hints
mypy src/
```

## Support & Community

- 📖 **Documentation**: See [docs/](docs/) for detailed guides
- 🐛 **Issues**: [Report bugs](https://github.com/yourusername/prod_mara_ingestion/issues)
- 💡 **Discussions**: [Ask questions](https://github.com/yourusername/prod_mara_ingestion/discussions)
- 📧 **Email**: your-email@example.com

## Acknowledgments

Built with:
- [Surya OCR](https://github.com/VikParuchuri/surya) - Advanced document OCR
- [SentenceTransformers](https://www.sbert.net/) - Embedding generation
- [Qdrant](https://qdrant.tech/) - Vector database
- [marker-pdf](https://github.com/VikParuchuri/marker) - PDF to Markdown conversion
