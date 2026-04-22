# Troubleshooting & Debugging Guide

## Quick Reference

### Common Issues by Symptom

| Symptom | Likely Cause | Solution |
|---------|--------------|----------|
| Pipeline hangs at OCR | GPU memory full | Reduce image_scale or use CPU |
| No markdown output | PDF corrupted | Check original PDF in reader |
| Headers not detected | Text not marked bold in OCR | Check debug PNGs |
| Missing text | OCR confidence too low | Increase image_scale |
| Duplicate chunks | Table linearization error | Check source markdown |
| Low recall score | Wrong embedding model | Try larger model or different chunking |
| Qdrant connection refused | Service not running | `make docker-up` |
| Out of memory during vectorization | Batch size too large | Reduce batch_size in config |

---

## Stage-by-Stage Debugging

### Stage 1: Extraction (OCR)

#### Issue: "Unable to load PDF"

**Symptoms**: Error message like "PDF parsing failed"

**Root Causes**:
- PDF is corrupted or password-protected
- Unsupported PDF format (too old/new)
- File permissions issue

**Debug Steps**:
```bash
# 1. Check PDF opens in system viewer
open data/raw/file.pdf

# 2. Verify file integrity
file data/raw/file.pdf

# 3. Try with different PDF parser
pdfinfo data/raw/file.pdf
```

**Solutions**:
- Re-save PDF from source
- Try PDF conversion tool (PDF → PDF)
- Run with `--verbose` flag for detailed output

#### Issue: "OCR Confidence too low (< 0.5)"

**Symptoms**: OCR results have low confidence scores; many text lines have <0.5 confidence

**Root Causes**:
- PDF has poor quality/low DPI
- Scanned document with bad lighting
- Unusual fonts or non-English text
- Image scale too low

**Debug Steps**:
```bash
# 1. Check confidence distribution
python -c "
import json
ocr = json.load(open('data/ocr/file_ocr.json'))
confidences = [l['confidence'] for p in ocr for l in p['text_lines']]
print(f'Avg: {sum(confidences)/len(confidences):.2f}')
print(f'Min: {min(confidences):.2f}')
print(f'Max: {max(confidences):.2f}')
"

# 2. Visual inspection
open data/ocr/file/debug_visualizations/  # View debug PNGs
```

**Solutions**:
- Increase `image_scale` in config (higher = slower but better quality)
  ```yaml
  ocr:
    image_scale: 3.0  # From 2.0
  ```
- Pre-process PDF: increase DPI, improve contrast
- Use GPU acceleration for better detection
  ```yaml
  ocr:
    device: "cuda"  # or "mps" for Apple Silicon
  ```

#### Issue: "Missing text on certain pages"

**Symptoms**: Some pages have little/no text extracted

**Root Causes**:
- Page is image-heavy with minimal text
- OCR model missed text due to layout
- Page is blank or contains only images

**Debug Steps**:
```bash
# 1. Check which pages have missing text
python -c "
import json
ocr = json.load(open('data/ocr/file_ocr.json'))
for i, page in enumerate(ocr, 1):
    lines = len(page.get('text_lines', []))
    print(f'Page {i}: {lines} text lines')
"

# 2. Visually inspect debug PNG
open "data/ocr/file/debug_visualizations/file_page_XX_debug.png"
```

**Solutions**:
- This may be expected (content is images)
- Verify with debug PNG visualization
- If text should be there: increase confidence threshold relaxation
- Consider supplementing with document structure OCR

---

### Stage 2: Conversion

#### Issue: "Headers not detected correctly"

**Symptoms**: Important section headers are not converted to markdown headers

**Root Causes**:
- Text not marked as bold in OCR
- Header heuristics don't match document style
- Unusual formatting or fonts

**Debug Steps**:
```bash
# 1. Check OCR JSON for bold markers
python -c "
import json
ocr = json.load(open('data/ocr/file_ocr.json'))
page = ocr[0]
for line in page['text_lines'][:10]:
    if '<b>' in line['text']:
        print(f'Bold: {line[\"text\"][:50]}')
"

# 2. Compare OCR vs converted markdown
echo "=== OCR Text ===" && head data/ocr/file_ocr.json | jq '.[] | .text_lines[0]'
echo "=== Converted ===" && head -20 data/markdown/file_converted.md
```

**Solutions**:
- Increase `image_scale` to improve OCR bold detection
- Adjust header detection heuristics in `surya_converter.py`
- Manually fix critical headers in markdown (Stage 3)
- Document expected header patterns for future processing

#### Issue: "Page markers missing"

**Symptoms**: Converted markdown has no `<!-- PAGE: N -->` comments

**Root Causes**:
- Feature not enabled in conversion config
- Bug in page number tracking

**Debug Steps**:
```bash
grep "PAGE:" data/markdown/file_converted.md
# Should see: <!-- PAGE: 1 -->, <!-- PAGE: 2 -->, etc.
```

**Solutions**:
- Verify config: `include_page_markers: true`
- Re-run conversion stage
- Check `surya_converter.py` for page marker insertion code

---

### Stage 3: Cleaning

#### Issue: "Lost content after cleaning"

**Symptoms**: Cleaning removes legitimate content

**Root Causes**:
- Cleaning rules too aggressive
- Text matches cleaning patterns unintentionally
- Table with important data linearized incorrectly

**Debug Steps**:
```bash
# 1. Compare sizes
wc -c data/markdown/file_converted.md data/cleaned/file_cleaned.md

# 2. Find what was removed
diff -u data/markdown/file_converted.md data/cleaned/file_cleaned.md | grep "^-"

# 3. Check table linearization
grep "^|" data/markdown/file_converted.md  # Original tables
grep -A 2 "^|" data/cleaned/file_cleaned.md  # After cleaning
```

**Solutions**:
- Review cleaned output for missing content
- Adjust cleaning rules if too aggressive:
  ```python
  # Modify src/processors/cleaner.py
  # Disable specific cleaning rule if problematic
  # E.g., comment out table linearization
  ```
- Manually fix critical sections
- Document edge cases for future improvements

#### Issue: "Special characters corrupted"

**Symptoms**: Accents, non-ASCII characters appear as ???

**Root Causes**:
- Encoding issue in pipeline
- PDF extraction lost character metadata

**Debug Steps**:
```bash
# Check file encoding
file -bi data/cleaned/file_cleaned.md
# Should show: text/plain; charset=utf-8

# Check for encoding errors
python -c "
with open('data/cleaned/file.md', 'r', encoding='utf-8', errors='replace') as f:
    content = f.read()
    if '?' in content and 'français' in content:
        print('Encoding corruption detected')
"
```

**Solutions**:
- Ensure UTF-8 encoding throughout pipeline
- In Python file operations:
  ```python
  open(file, 'r', encoding='utf-8')
  ```
- For Markdown files:
  ```yaml
  # Add to config
  text_encoding: utf-8
  ```

---

### Stage 4: Chunking

#### Issue: "Page numbers all 1"

**Symptoms**: All chunks have `page_number: 1`

**Root Causes**:
- Page markers not in markdown
- Page marker parsing broken
- Default value not working

**Debug Steps**:
```bash
# 1. Check if page markers exist
grep "PAGE:" data/cleaned/file_cleaned.md | head

# 2. Check parsing code
python -c "
import json
chunks = json.load(open('data/chunks/file_chunks.json'))
page_nums = [c['page_number'] for c in chunks['chunks']]
print(f'Unique pages: {set(page_nums)}')
"

# 3. Test marker parsing directly
python -c "
import re
text = '''<!-- PAGE: 1 -->
Content
<!-- PAGE: 2 -->
More content'''
for line in text.split('\n'):
    m = re.match(r'^<!-- PAGE: (\d+) -->$', line)
    if m:
        print(f'Found page: {m.group(1)}')
"
```

**Solutions**:
- Verify conversion stage created page markers (Stage 2)
- Re-run pipeline from conversion stage:
  ```bash
  python scripts/run_pipeline.py --skip-stages ocr
  ```
- Check chunker regex pattern in code
- Manually add page markers if missing:
  ```bash
  # Edit cleaned markdown
  # Add <!-- PAGE: N --> at appropriate locations
  ```

#### Issue: "Chunks too small/large"

**Symptoms**: Chunks are mostly tiny or mostly huge

**Root Causes**:
- `max_tokens` configuration too restrictive
- Atomic block detection too aggressive
- Document has unusual structure

**Debug Steps**:
```bash
# 1. Analyze chunk distribution
python -c "
import json
chunks = json.load(open('data/chunks/file_chunks.json'))
sizes = [len(c['content'].split()) for c in chunks['chunks']]
import statistics
print(f'Mean: {statistics.mean(sizes):.0f} words')
print(f'Median: {statistics.median(sizes):.0f} words')
print(f'Min: {min(sizes)} words')
print(f'Max: {max(sizes)} words')
"

# 2. Check config
grep "max_tokens\|chunk_size" config/settings.yaml
```

**Solutions**:
- Adjust `max_tokens` in config:
  ```yaml
  chunking:
    max_tokens: 1024  # From 512 if too small
  ```
- Re-run chunking:
  ```bash
  python scripts/run_pipeline.py --skip-stages ocr,convert,clean
  ```
- Check for lists/code blocks (atomic blocks):
  ```bash
  grep -E "^[-*+]\s|^```|^\d+\." data/cleaned/file.md | head
  ```

#### Issue: "Context breadcrumbs missing"

**Symptoms**: Chunks don't have proper context in `context` field

**Root Causes**:
- Headers not properly parsed
- Chunker bug in context extraction
- Document missing structure

**Debug Steps**:
```bash
# 1. Check cleaned markdown has headers
grep "^#" data/cleaned/file.md

# 2. Check chunks have context
python -c "
import json
chunks = json.load(open('data/chunks/file_chunks.json'))
contexts = [c['context'] for c in chunks['chunks']]
print(f'Contexts with value: {sum(1 for c in contexts if c)}')
print(f'Empty contexts: {sum(1 for c in contexts if not c)}')
"
```

**Solutions**:
- Ensure markdown has proper header structure
- Check chunker `_parse_sections()` logic
- Document structure requirement:
  ```markdown
  # Level 1 Header
  ## Level 2 Header
  ### Level 3 Header
  Content here...
  ```

---

### Stage 5: Vectorization

#### Issue: "Connection refused to Qdrant"

**Symptoms**: Error: "Failed to connect to http://localhost:6333"

**Root Causes**:
- Qdrant service not running
- Wrong URL in config
- Network issues

**Debug Steps**:
```bash
# 1. Check if running
docker ps | grep qdrant

# 2. Try connection
curl http://localhost:6333/health

# 3. Check config
grep "qdrant_url" config/settings.yaml
```

**Solutions**:
```bash
# Start Qdrant
make docker-up

# Or manually
docker-compose -f infra/docker-compose.yaml up -d

# Verify running
curl http://localhost:6333/readyz
```

#### Issue: "Out of memory during embedding"

**Symptoms**: Process killed, "Killed" message, or memory errors

**Root Causes**:
- Batch size too large
- Embedding model too large
- System memory insufficient

**Debug Steps**:
```bash
# 1. Check system memory
free -h  # Linux
vm_stat  # macOS
Get-ComputerInfo  # Windows

# 2. Check batch size in config
grep "batch_size" config/settings.yaml

# 3. Monitor during run
while true; do free -h | grep Mem; sleep 1; done
```

**Solutions**:
- Reduce batch size:
  ```yaml
  vectorization:
    batch_size: 32  # From 64
  ```
- Use smaller embedding model:
  ```yaml
  model_name: "sentence-transformers/all-MiniLM-L6-v2"  # 22MB
  ```
- Process fewer files at once
- Increase system RAM or use cloud resources

#### Issue: "Embeddings have NaN values"

**Symptoms**: Qdrant contains vectors with NaN (not-a-number) values

**Root Causes**:
- Encoding failed for specific text
- Model internal error
- Data corruption

**Debug Steps**:
```python
import json
import math

chunks = json.load(open('data/chunks/file_chunks.json'))
for i, chunk in enumerate(chunks['chunks']):
    try:
        model = SentenceTransformer("BAAI/bge-small-en-v1.5")
        embedding = model.encode(chunk['content'])
        if any(math.isnan(x) for x in embedding):
            print(f"Chunk {i} has NaN values")
    except Exception as e:
        print(f"Chunk {i} encoding failed: {e}")
```

**Solutions**:
- Sanitize chunk content:
  ```python
  chunk['content'] = chunk['content'].replace('\\x00', '')
  ```
- Skip problematic chunks:
  ```python
  try:
      embedding = model.encode(chunk['content'])
  except:
      continue  # Skip chunk
  ```
- Report upstream issue (cleaning or chunking)

---

## Evaluation & Quality Issues

### Issue: "Low Recall Score (< 70%)"

**Symptoms**: Evaluator reports Recall@5 below acceptable threshold

**Root Causes**:
- Chunks don't align with golden dataset expectations
- Embedding model not capturing semantics well
- Query phrasing doesn't match document language
- Chunking strategy loses critical context

**Debug Steps**:
```bash
# 1. Run evaluator with debug output
python benchmarking/evaluator.py --verbose

# 2. Analyze MISS queries
# Look at: "Expected Pages: X | Got Pages: Y"

# 3. Check golden dataset alignment
python -c "
import json
golden = json.load(open('benchmarking/golden.json'))
chunks = json.load(open('data/chunks/file_chunks.json'))

for query in golden['queries'][:3]:
    print(f'Query: {query[\"query\"][:50]}')
    print(f'  Expected chunks: {query[\"relevant_chunks\"]}')
    print()
"
```

**Solutions** (in order of effectiveness):

1. **Improve chunking strategy**:
   - Increase `max_tokens` for more context per chunk
   - Verify headers are properly detected
   - Check atomic block detection isn't too aggressive

2. **Use better embedding model**:
   ```yaml
   # Trade: larger model = slower but more accurate
   model_name: "BAAI/bge-large-en-v1.5"  # 1024 dims vs 384
   ```

3. **Update golden dataset**:
   - Ensure `relevant_chunks` matches actual document chunks
   - Update `page_range` to match actual pages
   - Verify queries are reasonable

4. **Implement hybrid ranking**:
   ```python
   # In evaluator: combine semantic + keyword matching
   if "side effect" in query.lower():
       # Boost results containing "adverse" or "toxicity"
       results = sorted(results, key=lambda x: ...)
   ```

5. **Re-process pipeline**:
   ```bash
   make clean-all
   make vectorize
   python benchmarking/evaluator.py
   ```

### Issue: "False positives in search results"

**Symptoms**: Top results are semantically unrelated to query

**Root Causes**:
- Embedding model not semantically aligned
- Chunk context too vague
- Queries poorly phrased

**Debug Steps**:
```python
# Manual test
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("BAAI/bge-small-en-v1.5")

query = "treatment options"
chunk1 = "Treatment options include medication or surgery"  # Relevant
chunk2 = "The treaty option was discussed"  # False positive?

q_emb = model.encode(query)
c1_emb = model.encode(chunk1)
c2_emb = model.encode(chunk2)

from scipy.spatial.distance import cosine
print(f"Query → Chunk1: {1 - cosine(q_emb, c1_emb):.3f}")  # Should be high
print(f"Query → Chunk2: {1 - cosine(q_emb, c2_emb):.3f}")  # Should be low
```

**Solutions**:
- Add context to chunks (already done via breadcrumbs)
- Filter by semantic similarity threshold:
  ```python
  results = [r for r in results if r.score > 0.75]
  ```
- Use more specific queries
- Consider different embedding model (domain-specific)

---

## Performance Issues

### Issue: "Pipeline very slow (>1 hour for 50 pages)"

**Symptoms**: Pipeline takes excessive time

**Debug Steps**:
```bash
# 1. Time each stage
time python src/extractors/pdf_marker_v2.py data/raw/file.pdf
time python src/extractors/surya_converter.py
time python src/processors/cleaner.py
time python src/processors/chunker.py
time python src/storage/embedder.py
```

**Solutions**:
- **Extraction slow?** Use GPU or reduce `image_scale`
- **Embedding slow?** Batch larger chunks, use GPU
- **Qdrant slow?** Check network, use local instance
- See [Architecture guide](architecture.md) for optimization opportunities

---

## Logging & Diagnostics

### Enable Verbose Logging

```bash
python scripts/run_pipeline.py --verbose --log-level DEBUG
```

This will:
- Print detailed progress messages
- Log to file: `logs/pipeline_{timestamp}.log`
- Show stack traces on errors

### Inspect Logs

```bash
# View latest log
tail -f logs/pipeline_latest.log

# Search for errors
grep "ERROR\|CRITICAL" logs/pipeline_*.log

# Count by level
grep "INFO\|DEBUG\|WARN\|ERROR" logs/pipeline_latest.log | cut -d: -f1 | sort | uniq -c
```

---

## Getting Help

### Questions to Ask When Seeking Help

1. **Which stage is failing?** (extraction, conversion, cleaning, chunking, vectorization)
2. **What's the error message?** (provide full stack trace)
3. **What's the input?** (PDF size, number of pages, document type)
4. **What's the system?** (OS, Python version, available memory)
5. **What have you tried?** (help avoid duplicate suggestions)

### Example Issue Report

```
Stage: Vectorization (Stage 5)
Error: Out of memory during embedding
Input: 50-page medical report (~2MB PDF)
System: macOS, Python 3.10, 8GB RAM
Config: batch_size=64, model=BAAI/bge-small-en-v1.5
Tried: Reducing batch_size to 32 (still OOM)
```

### Resources

- [Data Flow](data_flow.md) - Understanding pipeline stages
- [Architecture](architecture.md) - Design decisions and structure
- [Storage](storage.md) - Qdrant configuration
- [Processor](processor.md) - Chunking details

---

## See Also

- Main [README.md](../README.md) - Project overview
- [scripts/inspect_pipeline.py](../scripts/inspect_pipeline.py) - Interactive debugging tool
