# Extraction Stage Documentation

## Overview

The extraction stage transforms PDF documents into structured OCR output. The pipeline uses **Surya OCR** for robust text detection and includes **debug visualizations** for quality assurance.

### Why Two Extractors?

The codebase contains two extraction approaches:
- **pdf_marker_v2.py** - Surya OCR + Pix2Struct (current production path)
- **base.py** - Base extractor interface

## PDF Marker V2 (Current Production)

Located in `src/extractors/pdf_marker_v2.py`

### Architecture

```
PDF File
    ↓
[Load PDF & Convert to Images]
    - Uses pypdfium2 for robust PDF rendering
    - Renders at 2x resolution for better OCR accuracy
    ↓
[Run Surya OCR]
    - Scene text detection (vision transformer)
    - Optical character recognition
    - Outputs: text_lines with bbox, confidence, polygons
    ↓
[Serialize to JSON]
    - Clean dictionary format
    - Preserves bounding boxes for layout reconstruction
    ↓
[Optional: Visualize Results]
    - Draws bboxes on page images
    - Saves debug PNGs for QA
    ↓
OCR JSON (data/ocr/{filename}_ocr.json)
```

### Key Components

#### 1. Initialize Models
```python
from src.extractors.pdf_marker_v2 import initialize_models

# Load ML models (one-time cost, ~30 seconds)
predictors = initialize_models(device="cpu")  # or "cuda", "mps"
```

**What it loads**:
- Surya detection model (scene text detection)
- Surya recognition model (character OCR)
- Pix2Struct model (table detection - optional)
- ~2-3GB memory footprint

#### 2. Load PDF Images
```python
from src.extractors.pdf_marker_v2 import load_pdf_images

images = load_pdf_images("data/raw/paper.pdf")
# Returns: [PIL.Image, PIL.Image, ...]
```

**Parameters**:
- `IMAGE_SCALE`: Rendering resolution multiplier (default: 2.0)
  - 1.0 = 72 DPI (fast, lower quality)
  - 2.0 = 144 DPI (balanced)
  - 3.0+ = 216+ DPI (slow, highest quality)

#### 3. Run OCR
```python
results = run_ocr_on_images(images, predictors)
# Returns: List[Surya.DetectedText result objects]
```

**Output per page**:
- `text_lines`: List of detected text regions
- `bbox`: [x1, y1, x2, y2] in pixel coordinates
- `confidence`: 0.0-1.0 OCR confidence
- `polygon`: [corner_points] for rotated text

#### 4. Serialize Results
```python
ocr_json = serialize_surya_results(results)
# Converts Surya objects to clean JSON
```

### Output Structure

**File**: `data/ocr/{filename}_ocr.json`

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
      {
        "text": "Patient Name: John Doe",
        "confidence": 0.92,
        "bbox": [50, 85, 300, 105],
        "polygon": [[50, 85], [300, 85], [300, 105], [50, 105]]
      }
    ]
  },
  {
    "page_number": 2,
    "image_bbox": [0, 0, 612, 792],
    "text_lines": [...]
  }
]
```

### Debug Visualizations

**Location**: `data/ocr/{filename}/debug_visualizations/`

Files generated:
- `{filename}_page_001_debug.png`
- `{filename}_page_002_debug.png`
- etc.

Each PNG shows:
- Original page image
- Colored bounding boxes around detected text
- Confidence scores displayed
- Layout structure visible

**Use Case**: Verify OCR quality before processing further.

### Configuration

From `config/settings.yaml`:

```yaml
ocr:
  enable_surya: true              # Use Surya OCR (vs other engines)
  device: "mps"                   # "cpu", "cuda", "mps" (Apple Silicon)
  image_scale: 2.0                # PDF rendering resolution multiplier
  enable_table_detection: true    # Detect and preserve tables
  confidence_threshold: 0.5       # Minimum confidence to include text
  save_debug_images: true         # Generate debug visualizations
```

### Performance Characteristics

| Metric | Value | Notes |
|--------|-------|-------|
| Speed | 20-30 sec / 50 pages | Single-threaded, CPU |
| RAM | 2-4 GB | Per process |
| GPU Support | Yes (CUDA, MPS) | ~5x faster |
| Text Accuracy | 95-99% | Depends on PDF quality |
| Layout Preservation | Very Good | Maintains spatial structure |

### Common Issues & Solutions

**Issue**: Low confidence scores
- **Cause**: Poor PDF quality, scanned documents
- **Solution**: Increase `image_scale` to 3.0 or 4.0

**Issue**: Missing text
- **Cause**: OCR model limitations on special fonts
- **Solution**: Check debug PNGs; may require manual annotation

**Issue**: Memory exhaustion
- **Cause**: Processing too many pages at once
- **Solution**: Batch smaller PDFs, use `device: "cpu"`

**Issue**: Slow processing
- **Cause**: No GPU acceleration
- **Solution**: Install `torch[cuda]` or use Apple Silicon MPS

### Advanced Usage

#### Batch Processing Multiple PDFs
```python
from pathlib import Path
from src.extractors.pdf_marker_v2 import PDFMarkerExtractorV2

extractor = PDFMarkerExtractorV2()
pdf_dir = Path("data/raw")

for pdf_file in pdf_dir.glob("*.pdf"):
    result = extractor.extract(pdf_file)
    print(f"✓ {pdf_file.name}: {len(result['pages'])} pages")
```

#### Custom Confidence Filtering
```python
# Post-process OCR to filter low-confidence text
for page in ocr_data:
    high_conf_lines = [
        line for line in page["text_lines"]
        if line["confidence"] >= 0.85
    ]
    page["text_lines"] = high_conf_lines
```

#### Extracting Specific Pages Only
```python
# Modify load_pdf_images to select page range
images = [imgs[i] for i in range(0, 10)]  # First 10 pages
```

## Base Extractor Interface

Located in `src/extractors/base.py`

Provides abstract base class for implementing custom extractors:

```python
from src.extractors.base import BaseExtractor

class MyExtractor(BaseExtractor):
    def extract(self, pdf_path: Path) -> Dict:
        # Implement custom extraction logic
        pass
```

**Required Methods**:
- `extract(pdf_path)` → Dict with 'content', 'metadata', 'output_file'

---

## Troubleshooting Extraction

### Verification Checklist
- [ ] OCR JSON files exist in `data/ocr/`
- [ ] Debug PNGs show correct text detection
- [ ] Confidence scores reasonable (>0.7 average)
- [ ] Page numbers match original PDF
- [ ] No truncated text at page boundaries

### Debugging Workflow
```bash
# 1. Check OCR JSON structure
python -c "import json; data=json.load(open('data/ocr/file_ocr.json')); print(f'Pages: {len(data)}'); print(json.dumps(data[0], indent=2)[:500])"

# 2. Visual inspection
# Open debug PNGs in Finder/Explorer
open data/ocr/file/debug_visualizations/

# 3. Re-run with verbose logging
python scripts/run_pipeline.py --verbose --skip-stages convert,clean,chunk,vectorize
```

---

## Next Steps

After extraction, output flows to **Stage 2: Conversion** where OCR JSON becomes readable Markdown.

See [processor.md](processor.md) for cleaning and chunking details.
### Issue: "marker is not installed"

```bash
pip install marker-pdf
```

### Issue: Out of Memory

Reduce batch size in settings.yaml:

```yaml
batch_size: 5
```

### Issue: Poor OCR Quality

For scanned PDFs with low quality:
1. Consider preprocessing with higher resolution
2. Increase DPI settings if available
3. Check if original PDF is corrupted

## Limitations

1. Complex scientific figures may not extract well (image extraction is literal)
2. Handwritten annotations are not extracted
3. Some embedded objects may be missed
4. Very large documents (1000+ pages) may cause memory issues

## Integration with Pipeline

The extraction stage outputs Markdown that feeds into the processing stage:

```
PDF Input
   |
   v
[PDFMarkerExtractor]
   - OCR text
   - Detect tables
   - Extract images
   |
   v
Markdown Output (data/interim/)
   |
   v
[TextCleaner + MarkdownChunker]
   - Clean phantom links
   - Hierarchical chunking
   |
   v
[Vectorization]
```

## Advanced Usage

### Custom Output Directory

```python
extractor = PDFMarkerExtractor(output_dir="/custom/path")
```

### Batch Processing

```python
from pathlib import Path

extractor = PDFMarkerExtractor(output_dir="data/interim")
pdf_dir = Path("data/raw")

for pdf_file in pdf_dir.glob("*.pdf"):
    result = extractor.extract(pdf_file)
    print(f"Processed: {result['metadata']['filename']}")
```

### Error Handling

```python
try:
    result = extractor.extract(pdf_file)
except FileNotFoundError:
    print(f"PDF not found: {pdf_file}")
except Exception as e:
    print(f"Extraction failed: {e}")
```

## Testing

Test PDF extraction:

```bash
make test-pdf
# Or
python tests/test_pdf_marker.py
```

This verifies:
- PDF file exists
- Marker library is installed
- Extraction produces valid Markdown
- Output directory structure is correct
