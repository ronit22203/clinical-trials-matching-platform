# Extraction Stage Documentation

## Overview

The extraction stage transforms PDF documents into structured OCR output. The pipeline uses **Surya v2** block layout and writes **debug visualizations** for quality assurance.

Recognition is not in-process MPS. `SuryaInferenceManager` spawns llama.cpp (`brew install llama.cpp` on Apple Silicon) or vLLM (NVIDIA). Set `data_ingestion.ocr.inference_backend` to `auto`, `llama.cpp`, or `vllm`.

## PDF Marker V2 (Current Production)

Located in `src/extractors/pdf_marker_v2.py`

### Architecture

```
PDF File
    ↓
[Load PDF & Convert to Images]
    - Uses pypdfium2
    - Renders at image_scale (default 2)
    ↓
[Surya v2 RecognitionPredictor]
    - One call returns layout blocks in reading order
    - Tables are HTML; pictures and figure grids are skipped
    ↓
[Serialize to JSON]
    - label, reading_order, html, bbox, confidence, skipped
    - Polygons are not stored
    ↓
[Optional: Visualize Results]
    - Green: confident block
    - Red: below confidence_threshold
    - Orange: skipped graphical block
    ↓
OCR JSON ({ocr_dir}/{filename}_ocr.json)
```

### Key Components

#### 1. Initialize Models
```python
from src.extractors.pdf_marker_v2 import initialize_models

models = initialize_models(device="cpu", inference_backend="auto")
predictor = models["recognition"]
```

`initialize_models` keeps the inference server alive for the process (`SURYA_INFERENCE_KEEP_ALIVE`).

#### 2. Load PDF Images
```python
from src.extractors.pdf_marker_v2 import load_pdf_images

images = load_pdf_images("data/raw/paper.pdf", image_scale=2, max_pages=None)
```

`image_scale` 2 is 144 DPI. `max_pages` stops rendering after that many pages.

#### 3. Run OCR and serialize
```python
from src.extractors.pdf_marker_v2 import run_ocr, serialize_surya_results

results = run_ocr(images, predictor)
ocr_json = serialize_surya_results(results)
```

### Output Structure

```json
[
  {
    "page_number": 1,
    "image_bbox": [0, 0, 1224, 1584],
    "blocks": [
      {
        "label": "SectionHeader",
        "reading_order": 0,
        "html": "Methods",
        "bbox": [50, 50, 200, 75],
        "confidence": 0.95,
        "skipped": false
      },
      {
        "label": "Table",
        "reading_order": 1,
        "html": "<table><tr><td>Low</td><td>High</td></tr></table>",
        "bbox": [50, 90, 400, 200],
        "confidence": 0.91,
        "skipped": false
      },
      {
        "label": "Picture",
        "reading_order": 2,
        "html": "",
        "bbox": [50, 220, 400, 400],
        "confidence": null,
        "skipped": true
      }
    ]
  }
]
```

`bbox` is `[x0, y0, x1, y1]` in pixels of the rendered page. `skipped: true` means the block was a graphical region and was not OCR'd. Do not fill those regions in by guessing symbols.

### Debug Visualizations

**Location**: `{ocr_dir}/{filename}/debug_visualizations/`

Files: `{filename}_page_001_debug.png`, and one PNG per rendered page.

### Configuration

From `config/app.yaml` (`data_ingestion.ocr`):

```yaml
ocr:
  device: mps                  # torch device for leftover detection weights
  inference_backend: auto      # auto | llama.cpp | vllm
  image_scale: 2
  confidence_threshold: 0.8    # text blocks below this are omitted from Markdown
  save_debug_images: true
  max_pages: null
```

### Runtime

| Host | Backend |
|------|---------|
| Apple Silicon / CPU | llama.cpp (`llama-server` on `PATH`) |
| NVIDIA GPU | vLLM, spawned by Surya |

`device: mps` does not run recognition. A cold server start can take several minutes; later PDFs reuse it.

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
