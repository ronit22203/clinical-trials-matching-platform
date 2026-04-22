# Documentation Index

## Quick Navigation

### For First-Time Users
1. Start with [Architecture & System Design](architecture.md) - Understand the overall system
2. Read [Data Flow & Traceability](data_flow.md) - See how data moves through stages
3. Follow [Quick Start Guide](#quick-start-below) for hands-on setup

### For Implementation
- **Setting up**: See [Project README](../README.md)
- **Running OCR**: [Extraction Stage](extractor.md)
- **Cleaning & chunking**: [Processing Stage](processor.md)
- **Embedding & indexing**: [Storage & Vectorization](storage.md)
- **Querying**: [Retrieval & Query Guide](retrieval.md)

### For Troubleshooting
- **Stuck on an error?**: [Debugging & Troubleshooting](debugging.md)
- **Performance issues?**: See [Architecture - Performance Bottlenecks](architecture.md#performance-bottlenecks)
- **Low retrieval accuracy?**: See [Debugging - Evaluation Issues](debugging.md#evaluation--quality-issues)

### For Operations
- **Running full pipeline**: `python scripts/run_pipeline.py`
- **Managing Qdrant**: [Storage - QdrantManager](storage.md#qdrantmanager)
- **Monitoring health**: [Storage - Monitoring](storage.md#monitoring-and-maintenance)

---

## Documentation Structure

```
docs/
├── architecture.md          ← System design, class hierarchy, data flows
├── data_flow.md             ← Pipeline stages, file structure, naming conventions
├── extractor.md             ← PDF → OCR JSON conversion (Stage 1 + 2)
├── processor.md             ← Cleaning & chunking (Stage 3 + 4)
├── storage.md               ← Vectorization & Qdrant (Stage 5)
├── retrieval.md             ← Query API, evaluation, integration patterns
├── debugging.md             ← Troubleshooting, common issues, diagnostics
└── INDEX.md                 ← This file
```

---

## Stage-by-Stage Guide

### Stage 1 & 2: Extraction (PDF → OCR → Markdown)

**Files**: [extractor.md](extractor.md)

What happens:
1. PDF loaded and rendered to images
2. Surya OCR detects text and generates bounding boxes
3. OCR JSON serialized to disk with debug visualizations
4. OCR JSON converted to structured Markdown
5. Page markers (`<!-- PAGE: N -->`) added for traceability

**Input**: `data/raw/*.pdf`  
**Output**: 
- `data/ocr/*_ocr.json` - Raw OCR results
- `data/markdown/*_converted.md` - Markdown from OCR

**Key Configuration**:
```yaml
ocr:
  device: "mps"              # CPU or GPU acceleration
  image_scale: 2.0           # Higher = better quality, slower
```

**Common Issues**: Low OCR confidence, missing text, header detection

---

### Stage 3: Cleaning (Markdown → Cleaned Markdown)

**Files**: [processor.md](processor.md#stage-3-cleaning)

What happens:
1. Remove phantom image links and citation artifacts
2. Linearize Markdown tables to key-value format
3. Fix hyphenated words split across lines
4. Collapse excessive newlines
5. Normalize whitespace

**Input**: `data/markdown/*_converted.md`  
**Output**: `data/cleaned/*_cleaned.md`

**Rules Applied**:
- Remove `![...](...)` patterns
- Remove `[]()` dead links
- Convert tables: `| Col1 | Col2 |` → `Col1: val1, Col2: val2`
- Fix hyphenation: `word-\nbreak` → `wordbreak`
- Collapse newlines: `\n\n\n` → `\n\n`

**Key Configuration**:
```yaml
cleaning:
  linearize_tables: true
  fix_hyphenation: true
```

**Content Retention**: Typically 85-95% of converted markdown

---

### Stage 4: Chunking (Markdown → Chunks with Metadata)

**Files**: [processor.md](processor.md#stage-4-chunking)

What happens:
1. Parse Markdown into hierarchical sections
2. Extract page numbers from `<!-- PAGE: N -->` markers
3. Respect atomic blocks (lists, code, tables)
4. Split large sections by size while preserving context
5. Prepend breadcrumb paths to chunks

**Input**: `data/cleaned/*_cleaned.md`  
**Output**: `data/chunks/*_chunks.json`

**Example Chunk**:
```json
{
  "content": "Context: Clinical Findings > Test Results\n\nLab values show...",
  "context": "Clinical Findings > Test Results",
  "level": 2,
  "chunk_index": 3,
  "page_number": 5
}
```

**Key Configuration**:
```yaml
chunking:
  max_tokens: 512           # Chunk size limit
  include_page_numbers: true # Track source pages (NEW!)
```

---

### Stage 5: Vectorization (Chunks → Embeddings → Qdrant)

**Files**: [storage.md](storage.md)

What happens:
1. Load embedding model (BAAI/bge-small-en-v1.5, 384 dims)
2. Generate embeddings for each chunk
3. Prepare Qdrant points with metadata
4. Batch upsert to Qdrant vector database

**Input**: `data/chunks/*_chunks.json`  
**Output**: Qdrant collection `"medical_papers"`

**Performance**:
- Speed: 100-200 embeddings/sec (CPU), 1000+ (GPU)
- Memory: ~200MB for model + ~1-2GB working

**Key Configuration**:
```yaml
vectorization:
  model_name: "BAAI/bge-small-en-v1.5"
  batch_size: 64
  qdrant_url: "http://localhost:6333"
```

---

## Retrieval & Evaluation

**Files**: [retrieval.md](retrieval.md)

### Basic Query
```python
from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer

client = QdrantClient("http://localhost:6333")
model = SentenceTransformer("BAAI/bge-small-en-v1.5")

query_vector = model.encode("side effects of aspirin").tolist()
results = client.search("medical_papers", query_vector, limit=5)

for result in results:
    print(f"Score: {result.score:.3f}, Page: {result.payload['page_number']}")
```

### Evaluation
```bash
python benchmarking/evaluator.py
# Outputs: Recall@5 metric against golden dataset
```

---

## Key Features & Highlights

### 1. Page Number Tracking ✨
Every chunk knows which page it came from:
- Extracted from PDF by OCR
- Preserved through conversion (page markers)
- Included in Qdrant metadata
- Enables page-level filtering and evaluation

### 2. Hierarchical Context
Each chunk includes breadcrumb path:
```
"Context: Clinical Studies > Efficacy Results > Safety Analysis"
```
Helps LLMs and retrieval systems understand document structure.

### 3. Full Audit Trail
All intermediate outputs saved and inspectable:
- `data/ocr/` - Debug visualizations for OCR quality
- `data/markdown/` - Raw conversion output
- `data/cleaned/` - After cleaning
- `data/chunks/` - Final chunk JSON

### 4. Modular Architecture
Each stage independent and replaceable:
- Can skip stages (e.g., `--skip-ocr` if already done)
- Easy to parallelize
- Simple to integrate custom components

### 5. Production-Ready
- Configuration-driven (no code changes)
- Comprehensive error handling
- Logging and diagnostics
- Performance optimization strategies

---

## Configuration Guide

**File**: `config/settings.yaml`

```yaml
# OCR (Stage 1)
ocr:
  device: "mps"              # "cpu", "cuda", "mps"
  image_scale: 2.0           # PDF rendering scale
  enable_table_detection: true
  save_debug_images: true

# Cleaning (Stage 3)
cleaning:
  linearize_tables: true
  fix_hyphenation: true
  remove_empty_lines: true

# Chunking (Stage 4)
chunking:
  max_tokens: 512            # Tokens per chunk
  preserve_headers: true
  include_context: true
  include_page_numbers: true # NEW!

# Vectorization (Stage 5)
vectorization:
  model_name: "BAAI/bge-small-en-v1.5"
  qdrant_url: "http://localhost:6333"
  collection_name: "medical_papers"
  batch_size: 64
  embedding_dimension: 384
```

---

## File Organization

```
project_root/
├── data/
│   ├── raw/                 ← Input PDFs
│   ├── ocr/                 ← Stage 1 output (JSON + debug PNGs)
│   ├── markdown/            ← Stage 2 output (converted MD)
│   ├── cleaned/             ← Stage 3 output (cleaned MD)
│   └── chunks/              ← Stage 4 output (chunk JSON)
│
├── docs/
│   ├── architecture.md      ← System design
│   ├── data_flow.md         ← Pipeline overview
│   ├── extractor.md         ← Extraction details
│   ├── processor.md         ← Processing details
│   ├── storage.md           ← Vectorization details
│   ├── retrieval.md         ← Query guide
│   ├── debugging.md         ← Troubleshooting
│   └── INDEX.md             ← This file
│
├── src/
│   ├── extractors/          ← PDF → OCR → Markdown
│   ├── processors/          ← Cleaning & chunking
│   └── storage/             ← Vectorization & Qdrant
│
├── scripts/
│   ├── run_pipeline.py      ← Main entry point
│   ├── inspect_pipeline.py  ← Debugging tool
│   └── pipeline.sh          ← Bash wrapper
│
├── benchmarking/
│   ├── golden.json          ← Ground truth Q&A
│   └── evaluator.py         ← Evaluation metrics
│
├── config/
│   └── settings.yaml        ← Configuration
│
├── infra/
│   └── docker-compose.yaml  ← Qdrant setup
│
└── README.md                ← Project overview
```

---

## Common Tasks

### Run Full Pipeline
```bash
python scripts/run_pipeline.py
# Or with bash wrapper
./scripts/pipeline.sh
```

### Process Single PDF
```bash
python scripts/run_pipeline.py data/raw/myfile.pdf
```

### Skip Specific Stages
```bash
# Skip extraction if _ocr.json already exists
python scripts/run_pipeline.py --skip-stages extraction
```

### Clear & Rebuild Vectors
```bash
make clean-vectors
make vectorize
```

### Test Retrieval Quality
```bash
python benchmarking/evaluator.py
```

### Query Vector Database
```bash
curl -X POST "http://localhost:6333/collections/medical_papers/points/search" \
  -H "Content-Type: application/json" \
  -d '{"vector": [...], "limit": 5}'
```

### Monitor Qdrant
```bash
# Start service
make docker-up

# View logs
make docker-logs

# Stop service
make docker-down

# List collections
python -c "from qdrant_client import QdrantClient; c = QdrantClient('http://localhost:6333'); print([col.name for col in c.get_collections().collections])"
```

---

## Performance Benchmarks

### Processing Time (50-page medical document)
| Stage | Time | Bottleneck |
|-------|------|-----------|
| Extraction (OCR) | 20-30s | GPU acceleration helps |
| Conversion | <1s | Very fast |
| Cleaning | <1s | Very fast |
| Chunking | 1-2s | Moderate |
| Vectorization | 30-60s | Model inference (use batch & GPU) |
| **Total** | **~60s** | Extraction + Vectorization |

### Query Performance
| Operation | Latency |
|-----------|---------|
| Encode query | 50-100ms |
| Search Qdrant | 10-50ms |
| **Total** | 100-150ms |

### Memory Usage
| Component | RAM |
|-----------|-----|
| Embedding model | 200MB |
| Qdrant instance | 500MB - 2GB |
| Working memory | 1-2GB |
| **Total** | **2-4GB** |

---

## Troubleshooting Quick Links

| Issue | Link |
|-------|------|
| Pipeline hangs | [Debugging - Stage 1](debugging.md#stage-1-extraction-ocr) |
| Low OCR quality | [Extractor - Low Confidence](debugging.md#issue-ocr-confidence-too-low--05) |
| Missing headers | [Processor - Headers](debugging.md#issue-headers-not-detected-correctly) |
| Page numbers wrong | [Debugging - Page Numbers](debugging.md#issue-page-numbers-all-1) |
| Qdrant connection error | [Storage - Troubleshooting](storage.md#troubleshooting) |
| Out of memory | [Storage - OOM](debugging.md#issue-out-of-memory-during-embedding) |
| Low recall score | [Debugging - Evaluation](debugging.md#issue-low-recall-score--70) |

---

## Next Steps

1. **Getting Started?** → Read [Architecture](architecture.md) + [Data Flow](data_flow.md)
2. **Running Pipeline?** → See [project README](../README.md) for setup
3. **Integration?** → Check [Retrieval Guide](retrieval.md) for API examples
4. **Issues?** → Jump to [Debugging Guide](debugging.md)
5. **Optimization?** → See [Architecture - Performance](architecture.md#performance-bottlenecks)

---

## Documentation Status

**Last Updated**: December 2024  
**Version**: 1.0 - Comprehensive  
**Coverage**:
- 5-stage pipeline fully documented
- Page number tracking added
- Troubleshooting guides complete
- Architecture & design decisions explained
- Retrieval & evaluation covered
- Configuration guide provided
- Performance benchmarks included

---

## See Also

- [Project README](../README.md) - Overview and setup
- [Configuration](../config/settings.yaml) - Detailed settings
- [Main Pipeline Script](../scripts/run_pipeline.py) - Implementation
- [Evaluation Script](../benchmarking/evaluator.py) - Quality metrics
