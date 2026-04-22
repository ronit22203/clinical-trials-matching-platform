# Architecture & System Design

## System Architecture

The medical data ingestion pipeline follows a **modular, stage-based architecture** optimized for traceability, debugging, and production reliability.

```
┌─────────────────────────────────────────────────────────────────┐
│                        INPUT LAYER                              │
├─────────────────────────────────────────────────────────────────┤
│  Raw PDFs (data/raw/) ← Manual uploads, automated crawlers      │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│                    EXTRACTION LAYER                             │
├─────────────────────────────────────────────────────────────────┤
│  Surya OCR (pdf_marker_v2.py)                                   │
│  ├─ Renders PDF → Images (pypdfium2)                            │
│  ├─ Runs scene text detection                                   │
│  └─ Outputs: OCR JSON + debug PNGs                              │
│  ↓                                                              │
│  Output: data/ocr/{name}_ocr.json                               │
│          data/ocr/{name}/debug_visualizations/                  │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│                  FORMAT CONVERSION LAYER                        │
├─────────────────────────────────────────────────────────────────┤
│  SuryaToMarkdown (surya_converter.py)                           │
│  ├─ Parses OCR JSON                                             │
│  ├─ Infers structure (headers, paragraphs)                      │
│  ├─ Adds page markers: <!-- PAGE: N -->                         │
│  └─ Outputs: Markdown                                           │
│  ↓                                                              │
│  Output: data/markdown/{name}_converted.md                      │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│                   CLEANING LAYER                                │
├─────────────────────────────────────────────────────────────────┤
│  TextCleaner (cleaner.py)                                       │
│  ├─ Remove phantom images/links                                 │
│  ├─ Linearize tables                                            │
│  ├─ Fix hyphenation                                             │
│  ├─ Collapse newlines                                           │
│  └─ Outputs: Cleaned Markdown                                   │
│  ↓                                                              │
│  Output: data/cleaned/{name}_cleaned.md                         │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│                   CHUNKING LAYER                                │
├─────────────────────────────────────────────────────────────────┤
│  MarkdownChunker (chunker.py)                                   │
│  ├─ Parse hierarchical structure                                │
│  ├─ Extract page numbers from markers                           │
│  ├─ Apply size constraints                                      │
│  ├─ Prepend context breadcrumbs                                 │
│  └─ Outputs: Chunks with metadata                               │
│  ↓                                                              │
│  Output: data/chunks/{name}_chunks.json                         │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│                 VECTORIZATION LAYER                             │
├─────────────────────────────────────────────────────────────────┤
│  MedicalVectorizer (embedder.py)                                │
│  ├─ Load SentenceTransformer model                              │
│  ├─ Generate embeddings for chunks                              │
│  ├─ Create Qdrant points with metadata                          │
│  └─ Outputs: Indexed vectors                                    │
│  ↓                                                              │
│  Output: Qdrant collection "medical_papers"                     │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│                    RETRIEVAL LAYER                              │
├─────────────────────────────────────────────────────────────────┤
│  Qdrant Vector Database (HTTP API on :6333)                     │
│  ├─ Semantic search endpoint                                    │
│  ├─ Filtering and filtering operations                          │
│  └─ Integration with RAG applications                           │
└─────────────────────────────────────────────────────────────────┘
```

---

## Data Flow & Transformations

### Stage Transitions

Each stage transforms data in specific ways:

```
Stage 1 → Stage 2:  Serialization + Layout Inference
  {bbox, text, confidence} → {markdown headers, paragraphs}

Stage 2 → Stage 3:  Normalization
  {raw markdown} → {cleaned markdown}

Stage 3 → Stage 4:  Hierarchical Decomposition
  {full document} → {chunks with context paths + page numbers}

Stage 4 → Stage 5:  Vectorization + Indexing
  {chunks (text)} → {embeddings (384-dim vectors) + metadata}
```

### File Size Evolution

For a 50-page medical document:

```
PDF:              5 MB
OCR JSON:         2 MB   (structured text)
Converted MD:     1.2 MB (slightly larger than cleaned due to markers)
Cleaned MD:       1.0 MB (85-95% of converted)
Chunks JSON:      0.8 MB (50-100 chunks, metadata included)
Qdrant Index:     45 MB  (embeddings: 100 chunks × 384 dims × 4 bytes)
```

---

## Class Hierarchy & Responsibilities

```
┌─────────────────────────────────────────┐
│         Extraction Layer                │
├─────────────────────────────────────────┤
│  PDFMarkerExtractorV2                   │
│  ├─ load_pdf_images()      → [Images]   │
│  ├─ run_ocr_on_images()    → [Results]  │
│  └─ serialize_results()    → JSON       │
│                                         │
│  SuryaToMarkdown                        │
│  ├─ convert()              → Markdown   │
│  ├─ _process_page()        → Page MD    │
│  └─ _detect_headers()      → Headers    │
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│        Processing Layer                 │
├─────────────────────────────────────────┤
│  TextCleaner                            │
│  ├─ clean()                → Cleaned    │
│  ├─ _linearize_tables()    → Key-Value  │
│  └─ _remove_artifacts()    → Text       │
│                                         │
│  MarkdownChunker                        │
│  ├─ chunk()                → Chunks     │
│  ├─ _parse_sections()      → Sections   │
│  ├─ _create_section()      → Section    │
│  ├─ _split_large_section() → Chunks     │
│  └─ _is_atomic_block()     → Boolean    │
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│        Vectorization Layer              │
├─────────────────────────────────────────┤
│  MedicalVectorizer                      │
│  ├─ __init__()             → Init       │
│  ├─ process_file()         → Points     │
│  ├─ run()                  → Upsert     │
│  └─ _resolve_path()        → Path       │
│                                         │
│  ConfigLoader                           │
│  └─ load()                 → Config     │
│                                         │
│  QdrantManager                          │
│  ├─ list_collections()     → Stats      │
│  ├─ delete_collection()    → Status     │
│  └─ clear_collection()     → Status     │
└─────────────────────────────────────────┘
```

---

## Key Design Decisions

### 1. Modular Stages

**Why**: Each stage can be developed, tested, and debugged independently.

**Benefits**:
- Easy to swap components (e.g., different OCR engine)
- Intermediate outputs enable debugging
- Can reprocess from any stage
- Parallel development

**Trade-off**: More files to maintain

### 2. Explicit Metadata Tracking

**Why**: Every chunk includes source, page, context, and hierarchy information.

**Benefits**:
- Retrieve not just similarity but source info
- Enable filtering and ranking
- Full traceability for debugging
- Enables citation in downstream tasks

**Trade-off**: Slightly larger payload per chunk

### 3. Page Number Threading

**Why**: Add `<!-- PAGE: N -->` markers in conversion stage, parse through chunking, include in metadata.

**Benefits**:
- Know exactly which page each chunk came from
- Enable page-level filtering
- Support evaluation metrics
- Enable document navigation

**Trade-off**: Requires careful parsing

### 4. Hierarchical Context in Chunks

**Why**: Prepend breadcrumb paths (e.g., "Methods > Study Design") to every chunk.

**Benefits**:
- Embeddings understand document structure
- LLMs can reason about context
- Better ranking possible
- More semantic chunks

**Trade-off**: Slightly larger chunk size, less content per chunk

### 5. Async-Ready Architecture

**Why**: Pipeline is structured for easy parallelization.

**Example**:
```python
# Could parallelize across files
for pdf_file in pdf_files:
    result = process_pdf(pdf_file)  # Independent
```

**Current**: Sequential for simplicity
**Future**: Easy to add multiprocessing/threading

---

## Configuration Management

```
config/settings.yaml  ← Single source of truth
    ├─ ocr.*           (extraction parameters)
    ├─ conversion.*    (format conversion)
    ├─ cleaning.*      (cleaning rules)
    ├─ chunking.*      (chunking strategy)
    └─ vectorization.* (embedding & Qdrant)

┌─────────────────────────────────────────────┐
│  Each module loads config at initialization │
│  ConfigLoader.load() → YAML → Dict         │
│  ↓                                          │
│  Passed to class constructors              │
│  ↓                                          │
│  Enables flexibility without code changes   │
└─────────────────────────────────────────────┘
```

---

## Error Handling Strategy

```
Errors by Layer:

Extraction:
  ├─ PDF corruption         → Skip file, log
  ├─ OCR failure            → Retry or skip
  └─ Memory exhaustion      → Batch smaller PDFs

Conversion:
  ├─ Invalid OCR JSON       → Detailed error message
  ├─ Header detection edge cases → Default behavior
  └─ Character encoding     → UTF-8 default

Cleaning:
  ├─ Regex edge cases       → Graceful fallback
  └─ Table parsing errors   → Keep original

Chunking:
  ├─ Malformed markdown     → Treat as single chunk
  ├─ Missing headers        → Use default context
  └─ Page marker parsing    → Default to page 1

Vectorization:
  ├─ Model download failure → Retry with timeout
  ├─ Qdrant connection      → Detailed error + recovery
  ├─ Memory OOM             → Reduce batch size
  └─ Invalid embeddings     → Log and skip
```

---

## Performance Bottlenecks

### Current Bottlenecks (in order)

```
1. Embedding Generation  (40-50% of time)
   - Sequential processing
   - Can be parallelized
   - Can use GPU acceleration

2. PDF Loading/Rendering (15-25%)
   - OCR model initialization (one-time)
   - PDF image rendering per page

3. Text Cleaning         (10%)
   - Regex operations
   - Table linearization

4. Qdrant Indexing       (5%)
   - Network latency
   - Fast on local instance

5. Chunking              (<5%)
   - Usually fast
```

### Optimization Opportunities

**Short term** (easy):
- Enable GPU for embeddings (5x speedup)
- Batch processing (parallel embedding)
- Cache loaded models

**Medium term** (moderate effort):
- Parallelize PDF extraction
- Async Qdrant indexing
- Streaming output

**Long term** (architectural):
- Distributed processing (multiple machines)
- Message queue (Kafka/RabbitMQ)
- Incremental indexing

---

## Testing Strategy

### Unit Tests

Test individual components in isolation:

```python
# Test TextCleaner
def test_remove_phantom_links():
    cleaner = TextCleaner()
    assert cleaner.clean("text [](link) more") == "text  more"

# Test Chunker
def test_page_number_parsing():
    chunks = chunker.chunk("<!-- PAGE: 2 -->\n# Header\nContent")
    assert chunks[0]['page_number'] == 2
```

### Integration Tests

Test stages working together:

```python
# Test conversion → chunking
markdown = converter.convert(ocr_data)
chunks = chunker.chunk(markdown)
assert all('page_number' in c for c in chunks)
```

### End-to-End Tests

Test full pipeline:

```python
# Run complete pipeline on sample PDF
result = run_pipeline("tests/fixtures/sample.pdf")
assert result['chunks'] > 0
assert result['vectors'] == result['chunks']
assert all(c.payload['page_number'] >= 1 for c in qdrant_points)
```

### Benchmark Tests

Test performance:

```python
# Measure throughput
start = time.time()
vectorizer.run("tests/fixtures/")
duration = time.time() - start
throughput = len(vectors) / duration
assert throughput > 100  # vectors/second
```

---

## Production Deployment Checklist

### Pre-Deployment

- [ ] All unit tests passing
- [ ] Integration tests passing
- [ ] Config validated (no missing keys)
- [ ] Resource requirements met (CPU/RAM/disk)
- [ ] Docker/containerization ready
- [ ] Logging configured properly
- [ ] Error handling tested

### Deployment

- [ ] Backup existing Qdrant data
- [ ] Start Qdrant instance
- [ ] Verify database connectivity
- [ ] Run health check
- [ ] Process first batch
- [ ] Monitor for errors
- [ ] Verify embeddings in Qdrant

### Post-Deployment

- [ ] Monitor logs for errors
- [ ] Verify retrieval quality (run evaluator)
- [ ] Check query latency
- [ ] Monitor disk usage
- [ ] Test with production queries
- [ ] Document baseline metrics

---

## Future Improvements

### Planned Enhancements

1. **Incremental Indexing**
   - Only process new/modified PDFs
   - Update vectors instead of full rebuild

2. **Advanced Retrieval**
   - Hybrid search (semantic + keyword)
   - Multi-step retrieval (retrieve → rerank)
   - Similarity deduplication

3. **Scaling**
   - Multi-GPU support
   - Distributed Qdrant
   - Streaming pipelines

4. **Quality**
   - Ground truth evaluation
   - Automated failure detection
   - Continuous improvement loop

5. **Integration**
   - REST API for queries
   - Webhook notifications
   - Chat interface

---

## See Also

- [Data Flow](data_flow.md) - How data moves through stages
- [Extractor](extractor.md) - OCR and extraction details
- [Processor](processor.md) - Cleaning and chunking strategy
- [Storage](storage.md) - Vectorization and Qdrant setup
- [Retrieval](retrieval.md) - Query and evaluation details
