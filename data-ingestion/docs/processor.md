# Processing Stage Documentation

## Overview

The processing stage transforms raw OCR output into production-grade training data. It consists of **two distinct steps**:

1. **Conversion** - OCR JSON → Markdown (Stage 2)
2. **Cleaning** - Normalize Markdown (Stage 3)
3. **Chunking** - Split into context-aware chunks (Stage 4)

Together these stages ensure data quality and semantic preservation.

---

## Stage 2: Conversion (OCR JSON → Markdown)

Located in `src/extractors/surya_converter.py`

### Purpose
Convert raw Surya OCR output (bounding boxes, text fragments) into a readable, structured Markdown document.

### Key Features
- **Layout Inference** - Detects headers from bold text and positioning
- **Page Markers** - Includes `<!-- PAGE: N -->` metadata for traceability
- **Spatial Preservation** - Respects paragraph breaks and document structure
- **No Cleaning** - Raw conversion (cleaning happens in Stage 3)

### How It Works

#### Step 1: Sort by Reading Order
```
Lines sorted by:
  1. Y-coordinate (top to bottom)
  2. X-coordinate (left to right)
```
Ensures proper reading order even in multi-column layouts.

#### Step 2: Detect Headers
Uses heuristics to identify headers:
- **Bold + Specific Keywords** → Level 2 Header (e.g., "SECTION 1")
- **Bold + All Caps + Short** → Level 1 Header (e.g., "MEDICAL REPORT")
- **Bold + Other** → Emphasized text (e.g., "**Important Note**")

```python
# Before:
<b>MEDICAL REPORT</b>

# After:
# MEDICAL REPORT
```

#### Step 3: Detect Paragraph Breaks
Calculates vertical gaps between lines:
- Gap > 2x line height → New paragraph block
- Smaller gaps → Same paragraph (consecutive)

```python
# Before (raw):
text_line_1
text_line_2
[large gap]
text_line_3

# After (markdown):
text_line_1
text_line_2

text_line_3
```

#### Step 4: Add Page Markers
Each page starts with a metadata comment:
```markdown
<!-- PAGE: 1 -->

# MEDICAL REPORT
...

<!-- PAGE: 2 -->

## Clinical Findings
...
```

These markers are parsed by the chunker in Stage 4 to track page numbers.

### Output Structure

**File**: `data/markdown/{filename}_converted.md`

```markdown
<!-- PAGE: 1 -->

# MEDICAL REPORT

## Patient Demographics

Name: John Doe
DOB: 01/15/1980

## Clinical Findings

The patient presents with elevated blood pressure...

<!-- PAGE: 2 -->

### Test Results

Lab Values:
- WBC: 7.5 K/uL
- Hgb: 14.2 g/dL
```

### Configuration

```yaml
conversion:
  header_confidence: 0.8       # Threshold for header detection
  min_paragraph_gap: 2.0       # Line height multiplier for paragraph breaks
  include_page_markers: true   # Add <!-- PAGE: N --> comments
```

### Troubleshooting Conversion

**Issue**: Headers not detected
- **Cause**: Text not marked as bold in OCR
- **Solution**: Check debug PNGs; text styling may be lost in OCR

**Issue**: Wrong paragraph breaks
- **Cause**: Inconsistent spacing in original PDF
- **Solution**: Acceptable trade-off; cleaned in Stage 3

---

## Stage 3: Cleaning

Located in `src/processors/cleaner.py`

### Purpose
Normalize Markdown and remove artifacts introduced by OCR/conversion.

### Cleaning Rules

#### Rule 1: Remove Phantom Images
**Problem**: Marker sometimes creates image links without proper paths
```markdown
# Before:
![](some_image)
text content

# After:
text content
```

**Implementation**:
```python
text = re.sub(r'!\[.*?\]\(.*?\)', '', text)
```

#### Rule 2: Remove Phantom Citation Links
**Problem**: Citations `[1]` converted to broken links `[](1)`
```markdown
# Before:
Smith et al. [](citation) showed...

# After:
Smith et al. showed...
```

**Implementation**:
```python
text = re.sub(r'\[\]\([^)]*\)', '', text)
```

#### Rule 3: Linearize Markdown Tables
**Problem**: Markdown tables isolate cells, breaking RAG retrieval
```markdown
# Before:
| Drug      | Dosage | Side Effects  |
|-----------|--------|---------------|
| Aspirin   | 500mg  | Headache      |
| Ibuprofen | 200mg  | Nausea        |

# After:
Drug: Aspirin, Dosage: 500mg, Side Effects: Headache
Drug: Ibuprofen, Dosage: 200mg, Side Effects: Nausea
```

**Why**: RAG systems retrieve individual chunks. Table cells are too isolated; linearization creates larger semantic units.

**Implementation**:
```python
def _linearize_tables(self, text: str) -> str:
    """Convert markdown tables to key-value text format"""
    lines = text.split('\n')
    result = []
    i = 0
    
    while i < len(lines):
        line = lines[i]
        # Check if this is a table header
        if '|' in line and i + 1 < len(lines) and '---' in lines[i + 1]:
            headers = [h.strip() for h in line.split('|')[1:-1]]
            i += 2  # Skip separator
            
            # Process data rows
            while i < len(lines) and '|' in lines[i]:
                values = [v.strip() for v in lines[i].split('|')[1:-1]]
                row_text = ', '.join(f"{h}: {v}" for h, v in zip(headers, values))
                result.append(row_text)
                i += 1
        else:
            result.append(line)
            i += 1
    
    return '\n'.join(result)
```

#### Rule 4: Fix Hyphenated Words
**Problem**: PDF OCR splits words across lines
```markdown
# Before:
The drug showed improve-
ment in 50% of patients

# After:
The drug showed improvement in 50% of patients
```

**Implementation**:
```python
text = re.sub(r'(\w+)-\n(\w+)', r'\1\2', text)
```

#### Rule 5: Collapse Excessive Newlines
**Problem**: Multiple blank lines create structural noise
```markdown
# Before:
Conclusion.




## References

# After:
Conclusion.

## References
```

**Implementation**:
```python
text = re.sub(r'\n{3,}', '\n\n', text)
```

### Usage

```python
from src.processors.cleaner import TextCleaner

cleaner = TextCleaner()
cleaned_text = cleaner.clean(raw_markdown)
```

### Output Structure

**File**: `data/cleaned/{filename}_cleaned.md`

Same structure as converted Markdown, but normalized.

### Configuration

```yaml
cleaning:
  remove_empty_lines: true
  normalize_whitespace: true
  linearize_tables: true
  fix_hyphenation: true
```

### Verification

Check cleaning effectiveness:
```bash
# See original vs cleaned side-by-side
wc -c data/markdown/{file}_converted.md
wc -c data/cleaned/{file}_cleaned.md

# Calculate retention ratio
echo "scale=2; $(wc -c < data/cleaned/{file}_cleaned.md) / $(wc -c < data/markdown/{file}_converted.md) * 100" | bc
```

Typical retention: **85-95%** of content

---

## Stage 4: Chunking

Located in `src/processors/chunker.py`

### Purpose
Split documents into context-aware, semantic chunks suitable for embedding and retrieval.

### Core Innovation: Hierarchical Context Preservation

Traditional chunkers lose structure:
```
❌ Chunk 1: "The efficacy results were..."
❌ Chunk 2: "The side effects included..."
   → No context about which section these belong to
```

Our chunker preserves hierarchy:
```
✅ Chunk 1: "Context: Clinical Studies > Efficacy Results\n\nThe efficacy results were..."
✅ Chunk 2: "Context: Clinical Studies > Side Effects\n\nThe side effects included..."
   → Embedded context helps downstream tasks
```

### Chunking Strategy

#### Step 1: Parse Hierarchical Structure
```python
sections = self._parse_sections(text)
```

Builds a tree of sections based on Markdown headers:
```
├── # MEDICAL REPORT
│   ├── ## Clinical Findings
│   │   ├── ### Test Results
│   │   └── ### Diagnosis
│   └── ## Treatment Plan
└── # Appendix
```

#### Step 2: Extract Page Numbers
Parses `<!-- PAGE: N -->` comments:
```python
current_page_number = 1
for line in text.split('\n'):
    if re.match(r'^<!-- PAGE: (\d+) -->$', line):
        current_page_number = int(match.group(1))
```

Each section inherits the page number where it starts.

#### Step 3: Apply Chunking Rules

**Rule A: Preserve Atomic Blocks**
Never split lists, code blocks, or dense structured content:
```python
if re.search(r'^\s*[-*+]\s', text, re.MULTILINE):  # Markdown list
    return [whole_section]
if re.search(r'^\s*\d+\.\s', text, re.MULTILINE):  # Numbered list
    return [whole_section]
if '```' in text:  # Code block
    return [whole_section]
```

**Rule B: Size Constraint**
Keep chunks under max_tokens (default: 512):
```python
if estimate_tokens(chunk) <= max_tokens:
    return [chunk]
```

Token estimation uses rough formula: `tokens ≈ chars / 4`

**Rule C: Prepend Context Breadcrumb**
Each chunk includes its path in the document:
```python
chunk = f"Context: {context_path}\n\n{chunk_content}"
```

Examples:
- `"Context: Clinical Findings > Test Results"`
- `"Context: Appendix"`
- `"Context: Treatment Plan > Medications > Dosage"`

#### Step 4: Parameterize Chunks
Include metadata for retrieval:
```python
{
    'content': str,           # Actual text + context
    'context': str,           # Breadcrumb path
    'level': int,             # Header level (1-4)
    'chunk_index': int,       # Position in document
    'page_number': int        # Source page (NEW!)
}
```

### Output Structure

**File**: `data/chunks/{filename}_chunks.json`

```json
{
  "filename": "medical_report",
  "source_file": "medical_report_cleaned.md",
  "total_chunks": 42,
  "chunk_config": {
    "max_tokens": 512,
    "chunk_overlap": 300,
    "include_page_numbers": true
  },
  "chunks": [
    {
      "content": "Context: Clinical Studies > Efficacy Results\n\nThe drug showed 50% improvement in...",
      "context": "Clinical Studies > Efficacy Results",
      "level": 2,
      "chunk_index": 0,
      "page_number": 1
    },
    {
      "content": "Context: Clinical Studies > Side Effects\n\nGastrointestinal symptoms...",
      "context": "Clinical Studies > Side Effects",
      "level": 2,
      "chunk_index": 1,
      "page_number": 2
    }
  ]
}
```

### Configuration

```yaml
chunking:
  max_tokens: 512              # Maximum tokens per chunk
  chunk_overlap: 300           # Overlap between chunks (not currently used)
  preserve_headers: true       # Never split header lines
  include_context: true        # Prepend breadcrumb path
  include_page_numbers: true   # Track page_number in metadata
```

### Usage

```python
from src.processors.chunker import MarkdownChunker

chunker = MarkdownChunker(max_tokens=512)
chunks = chunker.chunk(cleaned_markdown)

# Each chunk:
# {
#     'content': '...',
#     'context': '...',
#     'level': 2,
#     'page_number': 3,
#     'chunk_index': 5
# }
```

### Analysis & Debugging

**Visualize chunk distribution**:
```bash
python -c "
import json
data = json.load(open('data/chunks/file_chunks.json'))
chunks = data['chunks']

# Count by level
from collections import Counter
levels = Counter(c['level'] for c in chunks)
print('Chunks by header level:', dict(levels))

# Average chunk size
sizes = [len(c['content']) for c in chunks]
print(f'Avg chunk size: {sum(sizes)/len(sizes):.0f} chars')

# Page distribution
pages = Counter(c['page_number'] for c in chunks)
print('Chunks per page:', dict(sorted(pages.items())))
"
```

### Troubleshooting Chunking

**Issue**: Chunks too small
- **Cause**: max_tokens too restrictive
- **Solution**: Increase max_tokens in config (e.g., 1024)

**Issue**: Chunks losing context
- **Cause**: Header structure unclear
- **Solution**: Check cleaned Markdown headers with `grep "^#"`

**Issue**: Page numbers all 1
- **Cause**: No page markers in markdown
- **Solution**: Verify conversion stage generated `<!-- PAGE: N -->` comments

---

## Full Pipeline Flow Diagram

```
OCR JSON (Surya output)
    ↓ [SuryaToMarkdown]
Converted Markdown + Page Markers
    ↓ [TextCleaner]
Cleaned Markdown
    ↓ [MarkdownChunker]
Chunks with:
  - Hierarchical context
  - Page numbers
  - Header levels
    ↓ [SentenceTransformer]
Embeddings (384 dims)
    ↓ [Qdrant Upsert]
Vector Database
```

---

## Next Steps

Chunked output flows to **Stage 5: Vectorization** where embeddings are generated and indexed.

See [storage.md](storage.md) for vectorization and Qdrant setup.
```

### Testing

```bash
make test-processors
```

Output shows:
- Original vs cleaned text length
- Sample of cleaned output
- Cleaning effectiveness metrics

## MarkdownChunker

Located in `src/processors/chunker.py`, this class implements context-aware hierarchical chunking.

### Problem Statement

Standard RAG chunking splits documents by token count (e.g., 500 tokens):

```python
# Standard RAG approach
chunk_1 = text[0:500]      # May end mid-sentence
chunk_2 = text[500:1000]   # May start mid-thought
```

This breaks semantic coherence. The LLM retrieves a chunk about "Efficacy Results" but doesn't know what drug or trial context it refers to.

### Solution: Context-Aware Hierarchical Chunking

Our chunker:
1. Respects document structure (headers, lists, code)
2. Prepends full breadcrumb context to each chunk
3. Never splits atomic blocks
4. Maintains semantic coherence

### Usage

```python
from src.processors.chunker import MarkdownChunker

chunker = MarkdownChunker(max_tokens=512)
chunks = chunker.chunk(markdown_text)

# Output: List of dicts with content, context, level
for chunk in chunks:
    print(f"Context: {chunk['context']}")
    print(f"Content: {chunk['content'][:200]}")
```

### Algorithm: Four-Step Process

#### Step 1: Parse Document Structure

Scans for header lines and builds a tree structure representing document hierarchy.

#### Step 2: Evaluate Section Size

Estimates tokens using rough approximation (1 token ~ 4 characters). Small sections (<512 tokens) are kept whole.

#### Step 3: Handle Large Sections

Large sections are split by paragraphs while preserving context and protecting atomic blocks.

#### Step 4: Build Final Chunks with Context

Each chunk gets prepended with full header breadcrumb for semantic context.

### Chunking Rules

**Rule A: Atomic Blocks**

Never split:
- Markdown lists (-, *, +, or numbered)
- Code blocks (```...```)
- Mathematical formulas
- Quoted text blocks

**Rule B: Whole Sections**

Keep <512 token sections intact to preserve coherence.

**Rule C: Context Prepending**

Every chunk includes full header breadcrumb:

```
Context: Clinical Studies > Results > Primary Endpoint

The trial enrolled 250 patients...
```

### Examples

#### Example 1: Medical Paper with Context

Input:
```markdown
# Efficacy of Drug X

## Methods

Study design involved...

## Results

### Primary Endpoint

The primary endpoint was met with p < 0.05.
```

Output chunks include:
```python
{
    'content': 'Context: Efficacy of Drug X > Results > Primary Endpoint\n\nThe primary endpoint was met...',
    'context': 'Efficacy of Drug X > Results > Primary Endpoint',
    'level': 3
}
```

#### Example 2: Protecting Atomic Blocks

Input:
```markdown
## Contraindications

- Do not use with hepatic impairment
- Avoid in pregnancy
- Contraindicated with certain medications
```

Output (list is never split):
```python
{
    'content': 'Context: Clinical Studies > Contraindications\n\n- Do not use...',
    'context': 'Clinical Studies > Contraindications',
    'level': 2
}
```

### Configuration

From `config/settings.yaml`:

```yaml
vectorization:
  chunk_size: 1500          # Max tokens per chunk
  chunk_overlap: 300        # Overlap between chunks
  headers_to_split: ["#", "##", "###"]  # Header levels to preserve
```

### Performance

For a typical 50-page medical paper:
- Parsing: <100ms
- Chunking: 500-1000ms
- Total overhead: <2 seconds

### Testing

```bash
make test-processors
```

Shows:
- Input markdown statistics
- Number of chunks created
- Sample chunks with context
- Estimated token distribution

## Integration with Pipeline

```
Markdown Input (from PDFMarkerExtractor)
   |
   v
[TextCleaner]
   - Remove phantom links
   - Linearize tables
   - Merge hyphenated words
   |
   v
Cleaned Markdown
   |
   v
[MarkdownChunker]
   - Parse structure
   - Respect headers
   - Prepend context
   - Split intelligently
   |
   v
Context-Aware Chunks
   |
   v
[Vectorization (see storage.md)]
```

## Limitations and Future Improvements

Current limitations:
- Header detection is basic (only # patterns)
- Token estimation is rough
- No special handling for very long paragraphs

Planned improvements:
- Configurable context format
- Support for different header styles
- Chunk overlap implementation
- Automatic chunk size optimization
- Semantic similarity-based splitting
