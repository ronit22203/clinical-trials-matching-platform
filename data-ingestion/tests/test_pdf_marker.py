#!/usr/bin/env python
"""
Test script for PDFMarkerExtractor
"""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config_loader import load_ingestion_config
from src.extractors.pdf_marker import PDFMarkerExtractor

if __name__ == "__main__":
    config = load_ingestion_config(project_root.parent / "config" / "app.yaml")
    
    input_dir = (project_root / config['input_dir']).resolve()
    output_dir = (project_root / config['output']['markdown_dir']).resolve()
    
    print("="*60)
    print("TESTING PDF MARKER EXTRACTOR")
    print("="*60 + "\n")
    
    # Find first PDF in input directory
    pdf_files = list(input_dir.glob("*.pdf"))
    
    if not pdf_files:
        print(f"✗ No PDF files found in: {input_dir}")
        print(f"\nPlease add PDF files to: {input_dir}")
        sys.exit(1)
    
    pdf_file = pdf_files[0]
    print(f"Found PDF: {pdf_file.name}")
    print(f"Output directory: {output_dir}\n")
    
    try:
        extractor = PDFMarkerExtractor(output_dir=str(output_dir))
        result = extractor.extract(pdf_file)
        print(f"✓ Extraction successful!")
        print(f"Content length: {len(result['content'])} characters")
        print(f"Metadata: {result['metadata']}")
    except Exception as e:
        print(f"✗ Extraction failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
