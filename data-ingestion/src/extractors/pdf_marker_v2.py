"""Surya v2 block-level OCR.

Recognition goes through SuryaInferenceManager, which spawns llama.cpp on
Apple Silicon or vLLM on NVIDIA. Pages are stored as layout blocks. Polygons
are not written into the OCR JSON.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import pypdfium2 as pdfium
from PIL import ImageDraw

# Add project root to path so imports work from any directory
project_root = Path(__file__).resolve().parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Surya's settings object reads SURYA_INFERENCE_BACKEND as "llamacpp", not "llama.cpp".
_BACKEND_ENV = {
    "llama.cpp": "llamacpp",
    "llamacpp": "llamacpp",
    "vllm": "vllm",
}

_SKIPPED_OUTLINE = "orange"


class Config:
    """Defaults used by the CLI. The pipeline passes config/app.yaml instead."""

    # Torch device for any detection weights the manager still loads.
    # Recognition itself is the inference backend, not in-process MPS.
    DEVICE = "mps"
    INFERENCE_BACKEND = "auto"
    IMAGE_SCALE = 2
    CONFIDENCE_THRESHOLD = 0.80


def apply_runtime_env(device: str | None, inference_backend: str | None) -> str:
    """Set process env before Surya constructs its settings object.

    ``auto`` leaves backend selection to Surya (vLLM when an NVIDIA GPU is
    present, llama.cpp otherwise). Any other value is written to
    ``SURYA_INFERENCE_BACKEND``. Keep-alive is always on so a warm API
    process does not tear the server down between PDFs.
    """
    backend = (inference_backend or "auto").strip().lower()
    os.environ["SURYA_INFERENCE_KEEP_ALIVE"] = "1"
    mapped = None
    if backend != "auto":
        mapped = _BACKEND_ENV.get(backend)
        if mapped is None:
            raise ValueError(
                f"Unknown inference_backend {inference_backend!r}. "
                "Expected 'auto', 'llama.cpp', or 'vllm'."
            )
        os.environ["SURYA_INFERENCE_BACKEND"] = mapped
    if device:
        os.environ["TORCH_DEVICE"] = device
    _patch_loaded_settings(device, mapped)
    return backend


def _patch_loaded_settings(device: str | None, backend: str | None) -> None:
    """Update Surya's singleton if it was imported before the env was set."""
    mod = sys.modules.get("surya.settings")
    if mod is None:
        return
    settings = mod.settings
    settings.SURYA_INFERENCE_KEEP_ALIVE = True
    if backend is not None:
        settings.SURYA_INFERENCE_BACKEND = backend
    if device:
        settings.TORCH_DEVICE = device


def initialize_models(device: str | None = None, inference_backend: str | None = None) -> dict:
    """Load one long-lived Surya v2 manager and recognition predictor."""
    if device is None:
        device = Config.DEVICE
    if inference_backend is None:
        inference_backend = Config.INFERENCE_BACKEND
    apply_runtime_env(device, inference_backend)
    from surya.inference import SuryaInferenceManager
    from surya.recognition import RecognitionPredictor

    print(
        f"Loading Surya v2 (torch device={device}, inference_backend={inference_backend})...",
        flush=True,
    )
    manager = SuryaInferenceManager()
    predictor = RecognitionPredictor(manager)
    print("Surya v2 ready.", flush=True)
    return {"manager": manager, "recognition": predictor}


def load_pdf_images(pdf_path, image_scale: float | None = None, max_pages: int | None = None):
    """Render a PDF to PIL images. ``max_pages`` caps how many pages are rendered."""
    scale = Config.IMAGE_SCALE if image_scale is None else image_scale
    print(f"Rendering PDF: {pdf_path}...")
    pdf = pdfium.PdfDocument(pdf_path)
    images = []
    try:
        for i, page in enumerate(pdf):
            if max_pages is not None and i >= int(max_pages):
                break
            bitmap = page.render(scale=scale, rotation=0)
            images.append(bitmap.to_pil())
    finally:
        pdf.close()
    print(f"Converted {len(images)} pages to images.")
    return images


def run_ocr(images, predictor):
    """Run block-level recognition. ``predictor`` is a RecognitionPredictor."""
    if not images:
        return []
    return predictor(images)


def _block_dict(block, index: int) -> dict:
    """Copy one block into the on-disk schema. Polygons are dropped."""
    if isinstance(block, dict):
        label = block.get("label") or ""
        html = block.get("html") or ""
        bbox = block.get("bbox") or [0, 0, 0, 0]
        confidence = block.get("confidence", None)
        skipped = bool(block.get("skipped", False))
        order = block.get("reading_order", index)
    else:
        label = getattr(block, "label", "") or ""
        html = getattr(block, "html", "") or ""
        bbox = list(block.bbox)
        confidence = getattr(block, "confidence", None)
        skipped = bool(getattr(block, "skipped", False))
        order = getattr(block, "reading_order", index)
    return {
        "label": label,
        "reading_order": int(order),
        "html": html,
        "bbox": [float(v) for v in bbox],
        "confidence": None if confidence is None else round(float(confidence), 4),
        "skipped": skipped,
    }


def _page_dict(result, page_number: int) -> dict:
    if isinstance(result, dict):
        blocks_in = result.get("blocks") or []
        image_bbox = result.get("image_bbox") or []
        number = result.get("page_number", page_number)
    else:
        blocks_in = result.blocks
        image_bbox = result.image_bbox
        number = page_number
    blocks = [_block_dict(block, i) for i, block in enumerate(blocks_in)]
    blocks.sort(key=lambda block: block["reading_order"])
    return {
        "page_number": number,
        "image_bbox": [float(v) for v in image_bbox],
        "blocks": blocks,
    }


def serialize_surya_results(results) -> list:
    """Convert page results into compact JSON-ready dicts, without polygons."""
    return [_page_dict(result, i + 1) for i, result in enumerate(results)]


def visualize_results(image, page_result, save_path, confidence_threshold: float = 0.80):
    """Draw one box per layout block.

    Green is at or above the confidence threshold (or confidence was not
    reported). Red is below the threshold. Orange is a skipped graphical block.
    """
    draw = ImageDraw.Draw(image)
    for block in _page_dict(page_result, 1)["blocks"]:
        if block["skipped"]:
            color = _SKIPPED_OUTLINE
        elif block["confidence"] is None or block["confidence"] >= confidence_threshold:
            color = "green"
        else:
            color = "red"
        box = [round(v) for v in block["bbox"]]
        if box[2] <= box[0] or box[3] <= box[1]:
            continue
        draw.rectangle(box, outline=color, width=2)
    image.save(save_path)


def save_debug_images(images, results, output_dir, stem: str, confidence_threshold: float = 0.80) -> list:
    """Write ``{stem}_page_NNN_debug.png`` and return per-page block counts."""
    debug_dir = Path(output_dir)
    debug_dir.mkdir(parents=True, exist_ok=True)
    page_info = []
    for i, (image, result) in enumerate(zip(images, results)):
        page = _page_dict(result, i + 1)
        visualize_results(
            image.copy(),
            page,
            debug_dir / f"{stem}_page_{i + 1:03d}_debug.png",
            confidence_threshold,
        )
        page_info.append({
            "page": i + 1,
            "blocks": len(page["blocks"]),
            "skipped": sum(1 for block in page["blocks"] if block["skipped"]),
        })
    return page_info


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract layout blocks from a PDF with Surya v2")
    parser.add_argument("input_pdf", type=str, help="Path to the input PDF file")
    args = parser.parse_args()

    input_file = Path(args.input_pdf)
    if not input_file.exists():
        print(f"Error: Input file '{args.input_pdf}' does not exist.")
        sys.exit(1)

    output_dir = Path(project_root) / "tests" / "test_data"
    output_dir.mkdir(parents=True, exist_ok=True)

    models = initialize_models()
    try:
        images = load_pdf_images(str(input_file))
        print(f"Running OCR on {len(images)} pages...")
        results = run_ocr(images, models["recognition"])
        json_output = serialize_surya_results(results)

        debug_dir = output_dir / "debug_viz"
        save_debug_images(images, results, debug_dir, input_file.stem, Config.CONFIDENCE_THRESHOLD)

        output_path = output_dir / f"{input_file.stem}_ocr.json"
        with open(output_path, "w", encoding="utf-8") as fh:
            json.dump(json_output, fh, indent=2, ensure_ascii=False)

        print(f"\nSuccess! JSON saved to: {output_path}")
        print(f"Check {debug_dir} to see the visualized layout boxes.")
    except Exception as exc:
        print(f"An error occurred: {exc}")
        import traceback
        traceback.print_exc()
