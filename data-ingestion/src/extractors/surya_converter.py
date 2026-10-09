"""Convert Surya v2 block JSON into Markdown.

Blocks are already in reading order. Graphical blocks are recorded as skip
markers. Their HTML is not copied into the document.
"""

from __future__ import annotations

import json
import sys
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

_GRAPHICAL_LABELS = {"Picture", "Figure", "Diagram", "Image"}
_CHROME_LABELS = {"PageHeader", "PageFooter", "Page-Header", "Page-Footer"}
_TEXT_LABELS = {
    "Text",
    "ListGroup",
    "List-Group",
    "Form",
    "Caption",
    "Footnote",
    "Equation",
    "Equation-Block",
    "Code",
    "Code-Block",
    "Bibliography",
    "ChemicalBlock",
    "Chemical-Block",
}


class SuryaToMarkdown:
    """Converts Surya v2 OCR JSON into structured Markdown.

    Args:
        config: Optional ingestion config (``data_ingestion`` from config/app.yaml).
                ``ocr.confidence_threshold`` drops low-confidence text blocks.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        ocr_cfg = (config or {}).get("ocr", {})
        self._confidence_threshold: float = float(ocr_cfg.get("confidence_threshold", 0.80))

    def convert(self, ocr_data: list[dict[str, Any]]) -> str:
        pages = []
        for i, page in enumerate(ocr_data):
            page_number = page.get("page_number", i + 1)
            body = self._process_page(page)
            pages.append(f"<!-- PAGE: {page_number} -->\n\n{body}")
        return "\n\n".join(pages)

    def _process_page(self, page: dict) -> str:
        blocks = page.get("blocks") or []
        ordered = sorted(
            enumerate(blocks),
            key=lambda pair: (pair[1].get("reading_order", pair[0]), pair[0]),
        )
        parts: list[str] = []
        for _, block in ordered:
            rendered = self._render_block(block)
            if rendered:
                parts.append(rendered)
        return "\n\n".join(parts)

    def _render_block(self, block: dict) -> str:
        label = block.get("label") or ""
        if label in _CHROME_LABELS:
            return ""
        if block.get("skipped") or label in _GRAPHICAL_LABELS:
            name = label or "Unknown"
            return f"<!-- layout:{name} skipped:true -->"
        if self._below_threshold(block):
            return ""
        html = block.get("html") or ""
        if label == "SectionHeader":
            text = _inline_text(html)
            return f"## {text}" if text else ""
        if label == "Table" or "<table" in html.lower():
            table = html_table_to_markdown(html)
            return table or _plain_text(html)
        if label in ("Equation", "Equation-Block"):
            return _plain_text(html)
        return _plain_text(html)

    def _below_threshold(self, block: dict) -> bool:
        if (block.get("label") or "") not in _TEXT_LABELS:
            return False
        confidence = block.get("confidence", None)
        if confidence is None:
            return False
        return float(confidence) < self._confidence_threshold


class _TableParser(HTMLParser):
    """Collect table cells in row-major order. Each cell is emitted once."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            text = " ".join("".join(self._cell).split()).replace("|", r"\|")
            self._row.append(text)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


class _TextParser(HTMLParser):
    """Flatten block HTML to text, keeping math source and list items."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "br":
            self.parts.append("\n")
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag in ("p", "div", "h1", "h2", "h3", "h4", "tr"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("p", "div", "li", "h1", "h2", "h3", "tr", "math"):
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)


def html_table_to_markdown(html: str) -> str:
    """Turn one HTML table into a GitHub-flavored pipe table."""
    if not html or "<table" not in html.lower():
        return ""
    parser = _TableParser()
    parser.feed(html)
    parser.close()
    if not parser.rows:
        return ""
    lines = []
    for index, row in enumerate(parser.rows):
        lines.append("| " + " | ".join(row) + " |")
        if index == 0:
            lines.append("| " + " | ".join("---" for _ in row) + " |")
    return "\n".join(lines)


def _plain_text(html: str) -> str:
    if not html:
        return ""
    parser = _TextParser()
    parser.feed(html)
    parser.close()
    text = unescape("".join(parser.parts))
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _inline_text(html: str) -> str:
    return " ".join(_plain_text(html).split())


def main():
    if len(sys.argv) < 2:
        print("Usage: python surya_converter.py <path_to_ocr_json>")
        print("Example: python surya_converter.py tests/test_data/Sample-filled-in-MR_ocr.json")
        sys.exit(1)

    json_path = Path(sys.argv[1])
    if not json_path.exists():
        print(f"Error: File not found: {json_path}")
        sys.exit(1)

    try:
        with open(json_path, "r", encoding="utf-8") as fh:
            ocr_data = json.load(fh)
    except json.JSONDecodeError as exc:
        print(f"Error: Invalid JSON file: {exc}")
        sys.exit(1)

    markdown_output = SuryaToMarkdown().convert(ocr_data)
    output_dir = Path("tests/test_markdown")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{json_path.stem}.md"
    output_path.write_text(markdown_output, encoding="utf-8")
    print(f"Successfully converted: {json_path}")
    print(f"Output saved to: {output_path}")
    print(f"Output size: {len(markdown_output)} characters")


if __name__ == "__main__":
    main()
