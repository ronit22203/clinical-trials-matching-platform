Yes — **Surya 2 is real**, and it is a genuine upgrade. Datalab shipped it as **`surya-ocr` v0.20.0 on 27 May 2026**. This platform is still on **v1 (`surya-ocr==0.17.0`)**.

v1 is a **stack of separate Torch models**: detect lines, then recognize them, plus optional layout/table models. That is exactly what `pdf_marker_v2.py` / the ingest server do (`load_predictors` → detection → recognition → `text_lines`). The `pdf_marker_v2` name is our extractor, not Surya 2.

v2 is a **single 650M VLM** that does layout, OCR, reading order, and tables in one model. Line detection stays a small Torch model. Recognition/layout/tables go through **vLLM (NVIDIA)** or **llama.cpp (CPU / Apple Silicon)**.

## Why v2 is better

**Quality.** They score **83.3% on olmOCR-bench**, best under 3B params, and close to models 5–50× larger. Datalab says the jump vs v1 is especially on **math, handwriting, tables, forms, and layout**. For this product that matters: filled medical forms and tables are exactly where line-based OCR plus Y-sort heuristics fall down.

Per-category on olmOCR `default`:

| ArXiv | Baseline | Headers | Tiny text | Multi-col | Old scans | Old math | Tables |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 88.3 | 99.7 | 92.5 | 93.7 | 82.4 | 41.8 | 81.4 | 86.6 |

Old scans are still weak (41.8%). Clean printed English / forms / tables is the win.

**Structure instead of heuristics.** v1 gives you `text_lines` with bbox + confidence. We then invent structure in `SuryaToMarkdown` (sort by Y, treat `<b>` as headers). v2 returns **`blocks` in reading order**, each with a **layout label** (`Text`, `SectionHeader`, `Table`, `Form`, `PageHeader`, `Equation`, `ChemicalBlock`, …) and **HTML** (tables as `<table>`, math as LaTeX). Header detection, column order, and table reconstruction would get much cleaner if we consumed that.

**Tables and math.** v1 does not give real table HTML. v2 can emit full tables with colspan/rowspan, and math without a second OCR pass.

**One model, 90+ languages.** English on their multilingual eval is **92.3%**. Language hints like `LANGS = ["en"]` are less of a thing.

**Code license.** v1 0.17 was **GPL-3.0**. v2 code is **Apache 2.0**; weights are modified OpenRAIL-M (research / personal / startups under $5M). That is a real product change, not just a model bump.

## What is not free

This is **not** `pip install surya-ocr==0.20.0`. Breaking changes:

- `load_predictors` / `FoundationPredictor` → `SuryaInferenceManager` + a spawned **vLLM or llama-server**
- `text_lines` → `blocks` + `html`
- Our converter, OCR JSON, bbox overlay, and GPU warmup path all assume v1 line boxes

**Runtime.** NVIDIA wants Docker + NVIDIA Container Toolkit. Mac/CPU wants `brew install llama.cpp`. In-process MPS Torch (what we use today) is gone for recognition.

**Mac speed.** Their published M1 number is **~0.11 pages/s** (p50 ~59s with `--parallel 8`). Fine for a laptop experiment; worse than v1 Torch/MPS for sequential local ingest unless you have a newer M-series chip and keep them. On an **RTX 5090** they claim **~5 pages/s** at high concurrency — that is the “really good news” hardware path (g4dn/T4 would be slower but still the intended server setup).

**Old scans** are still the weak cell. Scanned fax-quality charts may not magically get better.

## Bottom line for this platform

v2 is the right long-term OCR: better forms/tables/reading order, structured HTML, and a model small enough to self-host. For us it is a **pipeline rewrite**, not a version bump — `serialize_surya_results`, `SuryaToMarkdown`, the ingest API loop, and debug overlays all sit on `text_lines`.

If you want a next step, the useful experiment is: run a few of our medical PDFs through Surya 2 on the side, compare markdown vs current `_converted.md`, and only then decide whether to migrate the ingest service.

Surya v2 now writes layout blocks instead of a character stream. Both the ingest API and `run_pipeline.py` call the same path in `pdf_marker_v2.py`: one `RecognitionPredictor` pass, then compact JSON with `label`, `reading_order`, `html`, `bbox`, `confidence`, and `skipped`. Polygons are not stored.

Markdown follows that reading order. Section headers become headings, HTML tables become pipe tables with each cell kept once, and pictures or figures become `<!-- layout:… skipped:true -->` markers. Their HTML is not copied in. Page headers and footers are dropped. Text blocks under `confidence_threshold` are omitted; skipped figures are kept as markers.

`data_ingestion.ocr.inference_backend` is `auto` (`llama.cpp` or `vllm`). On this Mac, recognition needs `llama-server` from `brew install llama.cpp`. The API leaves that server running between PDFs. `device: mps` only applies to leftover torch detection weights.

`data-ingestion/tests/test_surya_blocks.py` passed (4 tests) without loading the model.

**Install conflict, left unresolved on purpose.** `surya-ocr==0.20.0` declares `httpx<0.28`. `google-genai==1.56.0` in the same requirements file requires `httpx>=0.28.1`, so `httpx` stays at `0.28.1`. `pip install -r data-ingestion/requirements.txt` will not resolve both pins in one environment.
