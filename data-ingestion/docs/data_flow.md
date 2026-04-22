# Data Flow & Traceability Guide

## Executive Summary

The medical data ingestion pipeline is a **5-stage architecture** that transforms PDFs into a production-grade vector database. Each stage produces **inspectable, debuggable artifacts** enabling full traceability from raw PDF to searchable embeddings.

**Key Features**:
- ✅ Full audit trail of transformations
- ✅ Page number tracking throughout pipeline
- ✅ Debug visualizations for QA
- ✅ Reversible processing (inspect any stage)
- ✅ Modular architecture (run individual stages)

## Pipeline Overview

```
PDF (data/raw/)
    ↓
[STAGE 1: OCR] → data/ocr/
    ├── {filename}_ocr.json                 ← Raw OCR output from Surya
    ├── {filename}/debug_visualizations/
    │   ├── {filename}_page_001_debug.png   ← Visual verification with bboxes
    │   ├── {filename}_page_002_debug.png
    │   └── ...
    └── {filename}_ocr_meta.json            ← OCR metadata & statistics
    ↓
[STAGE 2: CONVERT] → data/markdown/
    ├── {filename}_converted.md             ← Markdown from OCR JSON (with page markers)
    └── {filename}_convert_meta.json        ← Conversion statistics
    ↓
[STAGE 3: CLEAN] → data/cleaned/
    ├── {filename}_cleaned.md               ← Cleaned, normalized markdown
    └── {filename}_clean_meta.json          ← Cleaning statistics
    ↓
[STAGE 4: CHUNK] → data/chunks/
    ├── {filename}_chunks.json              ← JSON with chunks + metadata
    └── {filename}_chunk_meta.json          ← Chunking statistics
    ↓
[STAGE 5: VECTORIZE] → Qdrant Vector DB
    ├── Embeddings indexed with metadata    ← page_number, chunk_index, context
    └── Collection stats in Qdrant console
```

---

## Detailed File Structure

### Stage 1: OCR (`data/ocr/`)

**Purpose**: Extract text from PDF using Surya OCR  
**Input**: PDF files from `data/raw/`  
**Output**: JSON representation of OCR results  
**Time**: ~20-30 sec per 50-page PDF

```
data/ocr/
├── medical_report_ocr.json
│   └── Content: Array of pages with text_lines, bbox, confidence
│
└── medical_report/
    └── debug_visualizations/
        ├── medical_report_page_001_debug.png
        ├── medical_report_page_002_debug.png
        └── ...
```

**Sample JSON Structure**:
```json
[
  {
    "page_number": 1,
    "image_bbox": [0, 0, 612, 792],
    "text_lines": [
      {
        "text": "<b>MEDICAL REPORT</b>",
        "confidence": 0.95,
        "bbox": [50, 50, 200, 75],
        "polygon": [[50, 50], [200, 50], [200, 75], [50, 75]]
      },
      ...
    ]
  },
  ...
]
```

---

### Stage 2: Convert (`data/markdown/`)

**Purpose**: Convert OCR JSON to readable Markdown  
**Input**: `{filename}_ocr.json` from Stage 1  
**Output**: Raw Markdown with structure inferred from OCR  
**Time**: <1 sec per document

```
data/markdown/
└── medical_report_converted.md
```

**Features**:
- Infers headers from bold text & layout geometry
- Preserves spatial structure (paragraphs, gaps)
- No cleaning applied yet (raw conversion)

**Sample Output**:
```markdown
# MEDICAL REPORT

## Patient Demographics

Name: John Doe
DOB: 01/15/1980

## Clinical Findings

The patient presents with elevated blood pressure...
```

---

### Stage 3: Clean (`data/cleaned/`)

**Purpose**: Normalize and clean Markdown for better processing  
**Input**: `{filename}_converted.md` from Stage 2  
**Output**: Clean Markdown ready for chunking  
**Time**: <1 sec per document

```
data/cleaned/
└── medical_report_cleaned.md
```

**Cleaning Operations**:
1. Remove phantom image links: `![...](...)` → removed
2. Remove phantom citation links: `[]()` → removed
3. Linearize markdown tables → readable key-value format
4. Fix hyphenation: `treat-ment` → `treatment`
5. Collapse excessive newlines: `\n\n\n` → `\n\n`

**Size Reduction**: Typically 85-95% of original size retained

---

### Stage 4: Chunk (`data/chunks/`)

**Purpose**: Split into context-aware chunks for embeddings  
**Input**: `{filename}_cleaned.md` from Stage 3  
**Output**: JSON with chunks + hierarchical context  
**Time**: <1 sec per document

```
data/chunks/
└── medical_report_chunks.json
```

**Sample JSON Structure**:
```json
{
  "filename": "Sample-filled-in-MR",
  "source_file": "Sample-filled-in-MR_cleaned.md",
  "total_chunks": 42,
  "chunk_config": {
    "max_tokens": 1500,
    "chunk_overlap": 300
  },
  "chunks": [
    {
      "content": "Context: Clinical Studies > Efficacy Results\n\nThe drug showed 50% improvement in...",
      "context": "Clinical Studies > Efficacy Results",
      "level": 2
    },
    ...
  ]
}
```

**Chunking Strategy**:
- **Context-Aware**: Each chunk includes breadcrumb path (e.g., "Section > Subsection")
- **Header Respecting**: Never splits headers or atomic blocks
- **Size Bounded**: Each chunk ≤ max_tokens (configurable)
- **Overlapping**: Adjacent chunks may share sentences for continuity

---

### Stage 5: Vectorize (Qdrant Vector Database)

**Purpose**: Generate embeddings and index for semantic search  
**Input**: Chunks from Stage 4 (via `data/stage3_cleaned/` for re-processing)  
**Output**: Indexed vectors in Qdrant  
**Time**: ~100-500 vectors/sec (depends on batch size & GPU)

```
Qdrant (http://localhost:6333/)
└── Collection: "medical_papers"
    └── Points: 1000+ embedded chunks with metadata
        ├── vector: [0.123, -0.456, ...] (384 dims)
        ├── payload.source: "Sample-filled-in-MR"
        ├── payload.context: "Clinical Studies > Efficacy Results"
        └── payload.level: 2
```

**Embedding Model**: `BAAI/bge-small-en-v1.5` (384 dimensions)

---

## File Naming Convention

All files follow a consistent naming pattern for traceability:

```
{document_name}_{stage_suffix}.{extension}

Where stage_suffix is:
  _ocr        → Stage 1 (OCR JSON)
  _converted  → Stage 2 (Converted Markdown)
  _cleaned    → Stage 3 (Cleaned Markdown)
  _chunks     → Stage 4 (Chunked JSON)
```

Example pipeline for `medical_report.pdf`:
```
data/raw/medical_report.pdf
  ↓
data/ocr/medical_report_ocr.json
  ↓
data/markdown/medical_report_converted.md
  ↓
data/cleaned/medical_report_cleaned.md
  ↓
data/chunks/medical_report_chunks.json
  ↓
Qdrant (via Stage 5)
```

---

## Running the Pipeline

### Full Pipeline
```bash
python scripts/run_pipeline.py
```
Runs all 5 stages in sequence.

### Skip Specific Stages
```bash
# Skip OCR (assume _ocr.json already exists)
python scripts/run_pipeline.py --skip-ocr

# Skip conversion (assume _converted.md exists)
python scripts/run_pipeline.py --skip-convert

# Skip cleaning
python scripts/run_pipeline.py --skip-clean

# Skip chunking
python scripts/run_pipeline.py --skip-chunk

# Skip vectorization
python scripts/run_pipeline.py --skip-vectorize
```

### Custom Input Directory
```bash
python scripts/run_pipeline.py --input-dir /path/to/pdfs
```

---

## Debugging & Verification

### 1. Verify OCR Quality
Check debug visualizations with bounding boxes:
```
data/ocr/{filename}/debug_visualizations/
├── {filename}_page_001_debug.png  ← Green boxes = high confidence
├── {filename}_page_002_debug.png  ← Red boxes = low confidence
└── ...
```

### 2. Inspect Converted Markdown
```bash
# View raw conversion (before cleaning)
cat data/markdown/{filename}_converted.md
```

### 3. Compare Cleaning Impact
```bash
# Before cleaning
wc -c data/markdown/{filename}_converted.md

# After cleaning
wc -c data/cleaned/{filename}_cleaned.md
```

### 4. Review Chunk Quality
```bash
# View chunks in JSON format
cat data/chunks/{filename}_chunks.json | jq '.chunks[0:3]'
```

### 5. Query Qdrant
```bash
python -c "
from qdrant_client import QdrantClient
client = QdrantClient('http://localhost:6333')
collections = client.get_collections()
print(f'Collections: {[c.name for c in collections.collections]}')
"
```

---

## Pipeline Configuration

All settings are in `config/settings.yaml`:

```yaml
# OCR Settings
pdf_to_markdown:
  batch_size: 10
  verbose: true

# Cleaning Settings
preprocessing:
  remove_page_markers: true
  normalize_headings: true
  fix_hyphenation: true

# Chunking & Vectorization Settings
vectorization:
  chunk_size: 1500         # Tokens per chunk
  chunk_overlap: 300       # Overlap between chunks
  batch_size: 64           # Embedding batch size
  model_name: "BAAI/bge-small-en-v1.5"
  qdrant_url: "http://localhost:6333"
  collection_name: "medical_papers"
```

---

## Size & Performance Metrics

Typical benchmarks for a 50-page medical PDF:

| Stage | Time | Output Size |
|-------|------|-------------|
| 1. OCR | 20-30 sec | ~5 MB JSON |
| 2. Convert | 1 sec | ~1.5 MB Markdown |
| 3. Clean | 1 sec | ~1.2 MB Markdown (85% of original) |
| 4. Chunk | 1 sec | ~2 MB JSON (100+ chunks) |
| 5. Vectorize | 30 sec | N/A (Qdrant storage) |
| **TOTAL** | **~50-60 sec** | **~10 MB disk** |

---

## Example: End-to-End Trace

Starting with `patient_analysis.pdf`:

```
1. Place PDF
   data/raw/patient_analysis.pdf

2. Run Pipeline
   python scripts/run_pipeline.py

3. Inspect Outputs
   # OCR JSON (raw Surya output with 450+ text lines)
   data/ocr/patient_analysis_ocr.json (4.2 MB)
   data/ocr/patient_analysis/debug_visualizations/ (8 PNG files)
   
   # Converted Markdown (structure inferred, no cleaning)
   data/markdown/patient_analysis_converted.md (1.8 MB)
   
   # Cleaned Markdown (normalized, ready for chunking)
   data/cleaned/patient_analysis_cleaned.md (1.5 MB, 83% size)
   
   # Chunks JSON (112 chunks with context)
   data/chunks/patient_analysis_chunks.json (2.1 MB)
   
   # Qdrant Collection
   Collections → medical_papers → 112 points indexed

4. Search Vector DB
   from qdrant_client import QdrantClient
   client = QdrantClient("http://localhost:6333")
   results = client.search(...)  # Returns chunks with context
```

---

## Troubleshooting

### Low OCR Confidence
**Check**: `data/stage1_ocr/{filename}/debug_visualizations/` for red boxes  
**Fix**: Increase `IMAGE_SCALE` in `pdf_marker_v2.py` (from 2 to 3)

### Missing Headers in Converted Markdown
**Check**: Surya might not detect bold formatting correctly  
**Fix**: Adjust header detection heuristics in `surya_converter.py`

### Large Chunk Gaps
**Check**: `chunk_size` in `config/settings.yaml`  
**Fix**: Increase or decrease based on use case

### Qdrant Connection Failed
**Check**: Ensure Qdrant is running
```bash
make docker-up
```

---

## Summary

This pipeline provides **full traceability** with clear, readable artifacts at each stage:

✅ **Stage 1**: OCR JSON + debug visualizations  
✅ **Stage 2**: Converted markdown  
✅ **Stage 3**: Cleaned markdown  
✅ **Stage 4**: Chunked JSON with context  
✅ **Stage 5**: Vector database ready for RAG  

All files are saved with consistent naming and can be inspected independently for debugging and validation.
