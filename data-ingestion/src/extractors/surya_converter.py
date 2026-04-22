import json
import re
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional

class SuryaToMarkdown:
    """
    Converts raw Surya OCR JSON into structured Markdown.
    Leverages <b> tags and layout geometry to infer headers.

    Args:
        config: Optional full pipeline config dict (repo-root config/app.yaml loaded).
                When supplied, heuristic thresholds are read from config['conversion'].
    """

    def __init__(self, config: Dict[str, Any] = None):
        conv_cfg = (config or {}).get('conversion', {})
        self._gap_multiplier: float = conv_cfg.get('paragraph_gap_multiplier', 2.0)
        self._bold_header_max_chars: int = conv_cfg.get('bold_header_max_chars', 50)

    def convert(self, ocr_data: List[Dict[str, Any]]) -> str:
        markdown_output = []
        
        for i, page in enumerate(ocr_data):
            page_number = page.get('page_number', i + 1)
            page_text = self._process_page(page)
            # Add page metadata marker
            page_text = f"<!-- PAGE: {page_number} -->\n\n{page_text}"
            markdown_output.append(page_text)
            
        return "\n\n".join(markdown_output)

    def _process_page(self, page: Dict) -> str:
        lines = page.get("text_lines", [])
        if not lines:
            return ""

        # 1. Sort lines by Y-coordinate (Top to Bottom) to ensure reading order
        #    Secondary sort by X (Left to Right) for columns (simplified)
        lines.sort(key=lambda x: (x['bbox'][1], x['bbox'][0]))

        md_lines = []
        prev_bbox = None
        
        for i, line in enumerate(lines):
            text = line['text'].strip()
            bbox = line['bbox'] # [x1, y1, x2, y2]
            
            if not text:
                continue

            # --- Heuristic 1: Detect Headers ---
            # Strong signal: <b> tag wrapping the line
            is_bold = "<b>" in text and "</b>" in text
            clean_text = text.replace("<b>", "").replace("</b>", "").strip()
            
            # Logic: If Bold AND (starts with SECTION or is short/all-caps), it's a Header
            if is_bold:
                if clean_text.upper().startswith("SECTION"):
                    # Level 2 Header
                    clean_text = f"## {clean_text}"
                elif len(clean_text) < self._bold_header_max_chars and clean_text.isupper():
                    # Likely a Title (MEDICAL REPORT)
                    clean_text = f"# {clean_text}"
                else:
                    # Just bold text
                    clean_text = f"**{clean_text}**"
            
            # --- Heuristic 2: Paragraph Handling ---
            # Calculate vertical gap from previous line
            if prev_bbox:
                prev_bottom = prev_bbox[3]
                current_top = bbox[1]
                gap = current_top - prev_bottom
                
                # Estimate line height (bbox height)
                line_height = bbox[3] - bbox[1]
                
                # If gap exceeds multiplier * line_height, treat as new paragraph block
                if gap > (line_height * self._gap_multiplier):
                     md_lines.append("\n") # Add extra newline for spacing
                # If gap is small, it's the same paragraph (handled by join later)

            md_lines.append(clean_text)
            prev_bbox = bbox

        # Join lines. 
        # Note: We put double newlines for separated blocks in the logic above if needed, 
        # but for simple forms, joining by newline is safer to preserve key-values.
        return "\n".join(md_lines)


def main():
    if len(sys.argv) < 2:
        print("Usage: python surya_converter.py <path_to_ocr_json>")
        print("Example: python surya_converter.py tests/test_data/Sample-filled-in-MR_ocr.json")
        sys.exit(1)
    
    json_file = sys.argv[1]
    json_path = Path(json_file)
    
    if not json_path.exists():
        print(f"Error: File not found: {json_file}")
        sys.exit(1)
    
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            ocr_data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON file: {e}")
        sys.exit(1)
    
    converter = SuryaToMarkdown()
    markdown_output = converter.convert(ocr_data)
    
    # Generate output filename
    output_dir = Path("tests/test_markdown")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    output_filename = json_path.stem + ".md"
    output_path = output_dir / output_filename
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(markdown_output)
    
    print(f"✓ Successfully converted: {json_file}")
    print(f"✓ Output saved to: {output_path}")
    print(f"✓ Output size: {len(markdown_output)} characters")


if __name__ == "__main__":
    main()
