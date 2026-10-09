"""Surya v2 block schema: compact JSON and reading-order markdown."""

import json
import os

import pytest
from PIL import Image

from src.extractors.pdf_marker_v2 import (
    apply_runtime_env,
    serialize_surya_results,
    visualize_results,
)
from src.extractors.surya_converter import SuryaToMarkdown

_TABLE_HTML = (
    "<table>"
    "<tr><th colspan=\"2\">Risk</th><th>Note</th></tr>"
    "<tr><td>Low</td><td rowspan=\"2\">Shared</td><td>A</td></tr>"
    "<tr><td>High</td><td>B</td></tr>"
    "</table>"
)


class _Block:
    def __init__(self, **kwargs):
        self.label = kwargs["label"]
        self.reading_order = kwargs["reading_order"]
        self.html = kwargs.get("html", "")
        self.skipped = kwargs.get("skipped", False)
        self.confidence = kwargs.get("confidence", 0.9)
        self._bbox = kwargs["bbox"]
        self.polygon = [[0, 0], [1, 0], [1, 1], [0, 1]]

    @property
    def bbox(self):
        return self._bbox


class _Page:
    def __init__(self, blocks):
        self.blocks = blocks
        self.image_bbox = [0, 0, 100, 200]


def _sample_page() -> dict:
    return {
        "page_number": 1,
        "image_bbox": [0, 0, 800, 1000],
        "blocks": [
            {
                "label": "Text",
                "reading_order": 2,
                "html": "<p>Right column sentence</p>",
                "bbox": [400, 40, 700, 80],
                "confidence": 0.99,
                "skipped": False,
            },
            {
                "label": "SectionHeader",
                "reading_order": 0,
                "html": "<b>Methods</b>",
                "bbox": [10, 500, 200, 540],
                "confidence": 0.97,
                "skipped": False,
            },
            {
                "label": "Text",
                "reading_order": 1,
                "html": "<p>Left column sentence</p>",
                "bbox": [10, 200, 180, 240],
                "confidence": 0.96,
                "skipped": False,
            },
            {
                "label": "Table",
                "reading_order": 3,
                "html": _TABLE_HTML,
                "bbox": [10, 600, 400, 800],
                "confidence": 0.93,
                "skipped": False,
            },
            {
                "label": "Picture",
                "reading_order": 4,
                "html": "<p>+</p><p>!</p>",
                "bbox": [10, 10, 50, 30],
                "confidence": None,
                "skipped": True,
            },
            {
                "label": "Figure",
                "reading_order": 8,
                "html": "<p>green +</p>",
                "bbox": [60, 10, 90, 30],
                "confidence": 0.99,
                "skipped": False,
            },
            {
                "label": "PageFooter",
                "reading_order": 5,
                "html": "<p>doi watermark</p>",
                "bbox": [10, 900, 200, 930],
                "confidence": 0.99,
                "skipped": False,
            },
            {
                "label": "Text",
                "reading_order": 6,
                "html": "<p>illegible note</p>",
                "bbox": [10, 850, 80, 870],
                "confidence": 0.1,
                "skipped": False,
            },
            {
                "label": "Equation",
                "reading_order": 7,
                "html": r"<math>\[E = mc^2\]</math>",
                "bbox": [10, 820, 120, 845],
                "confidence": 0.95,
                "skipped": False,
            },
        ],
    }


def test_serialize_keeps_blocks_and_drops_polygons():
    page = _Page([
        _Block(
            label="Text",
            reading_order=0,
            html="<p>Hello</p>",
            bbox=[1, 2, 3, 4],
            confidence=0.91234,
        )
    ])
    payload = serialize_surya_results([page])
    encoded = json.dumps(payload)
    assert "text_lines" not in encoded
    assert "polygon" not in encoded
    block = payload[0]["blocks"][0]
    assert set(block) == {"label", "reading_order", "html", "bbox", "confidence", "skipped"}
    assert block["confidence"] == 0.9123
    assert payload[0]["image_bbox"] == [0.0, 0.0, 100.0, 200.0]
    assert "blocks" in payload[0]


def test_markdown_follows_reading_order_and_keeps_table_cells():
    markdown = SuryaToMarkdown(
        config={"ocr": {"confidence_threshold": 0.8}}
    ).convert([_sample_page()])

    methods = markdown.index("## Methods")
    left = markdown.index("Left column sentence")
    right = markdown.index("Right column sentence")
    risk = markdown.index("Risk")
    note = markdown.index("Note")
    low = markdown.index("Low")
    shared = markdown.index("Shared")
    cell_a = markdown.index("| A |")
    high = markdown.index("High")
    cell_b = markdown.index("| B |")
    picture = markdown.index("<!-- layout:Picture skipped:true -->")
    figure = markdown.index("<!-- layout:Figure skipped:true -->")
    equation = markdown.index(r"\[E = mc^2\]")

    assert methods < left < right < risk < note < low < shared < cell_a < high < cell_b
    assert cell_b < picture < equation < figure
    assert markdown.count("Shared") == 1
    assert "+" not in markdown
    assert "green" not in markdown
    # The only "!" characters are HTML comment openers, not guessed glyphs.
    assert markdown.count("!") == markdown.count("<!--")
    assert "doi watermark" not in markdown
    assert "illegible note" not in markdown


def test_debug_overlay_colors_skipped_blocks_separately(tmp_path):
    image = Image.new("RGB", (80, 40), "white")
    page = {
        "blocks": [
            {
                "label": "Text",
                "reading_order": 0,
                "html": "A",
                "bbox": [2, 2, 20, 16],
                "confidence": 0.95,
                "skipped": False,
            },
            {
                "label": "Text",
                "reading_order": 1,
                "html": "B",
                "bbox": [2, 22, 20, 36],
                "confidence": 0.2,
                "skipped": False,
            },
            {
                "label": "Picture",
                "reading_order": 2,
                "html": "",
                "bbox": [30, 2, 70, 30],
                "confidence": None,
                "skipped": True,
            },
        ]
    }
    path = tmp_path / "page.png"
    visualize_results(image, page, path, confidence_threshold=0.8)
    saved = Image.open(path)
    assert saved.getpixel((2, 2)) == (0, 128, 0)
    assert saved.getpixel((2, 22)) == (255, 0, 0)
    assert saved.getpixel((30, 2)) == (255, 165, 0)


def test_inference_backend_env(monkeypatch):
    monkeypatch.setenv("SURYA_INFERENCE_KEEP_ALIVE", "0")
    monkeypatch.setenv("TORCH_DEVICE", "cpu")
    monkeypatch.delenv("SURYA_INFERENCE_BACKEND", raising=False)

    apply_runtime_env("mps", "llama.cpp")
    assert os.environ["SURYA_INFERENCE_BACKEND"] == "llamacpp"
    assert os.environ["SURYA_INFERENCE_KEEP_ALIVE"] == "1"
    assert os.environ["TORCH_DEVICE"] == "mps"

    apply_runtime_env("cpu", "vllm")
    assert os.environ["SURYA_INFERENCE_BACKEND"] == "vllm"

    with pytest.raises(ValueError):
        apply_runtime_env("cpu", "cloud")
