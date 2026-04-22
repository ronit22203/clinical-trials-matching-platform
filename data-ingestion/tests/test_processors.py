#!/usr/bin/env python
"""
Test script for TextCleaner and MarkdownChunker
"""
import json
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def _rel(p: Path) -> Path:
    """Return path relative to project_root, or absolute if outside it."""
    try:
        return p.relative_to(project_root)
    except ValueError:
        return p

from src.config_loader import load_ingestion_config
from src.processors.cleaner import TextCleaner
from src.processors.chunker import MarkdownChunker
from src.extractors.surya_converter import SuryaToMarkdown

if __name__ == "__main__":
    config = load_ingestion_config(project_root.parent / "config" / "app.yaml")
    
    # Step 1: Convert OCR JSON to Markdown (if OCR file exists in test_data)
    print("="*60)
    print("STEP 1: CONVERTING OCR JSON TO MARKDOWN")
    print("="*60 + "\n")
    
    ocr_file = project_root / "tests" / "test_data" / "Sample-filled-in-MR_ocr.json"
    intermediate_dir = (project_root / config['output']['markdown_dir']).resolve()
    intermediate_dir.mkdir(parents=True, exist_ok=True)
    
    if ocr_file.exists():
        try:
            with open(ocr_file, 'r', encoding='utf-8') as f:
                ocr_data = json.load(f)
            
            converter = SuryaToMarkdown()
            markdown_output = converter.convert(ocr_data)
            
            # Save to interim directory
            md_output_file = intermediate_dir / (ocr_file.stem + ".md")
            with open(md_output_file, 'w', encoding='utf-8') as f:
                f.write(markdown_output)
            
            print(f"✓ Converted OCR JSON: {_rel(ocr_file)}")
            print(f"✓ Saved markdown to: {_rel(md_output_file)}")
            print(f"✓ Output size: {len(markdown_output)} characters\n")
        except Exception as e:
            print(f"✗ Error converting OCR: {e}\n")
    else:
        print(f"⚠ OCR file not found: {ocr_file}\n")
    
    # Step 2: Load markdown files for preprocessing
    print("="*60)
    print("STEP 2: LOADING MARKDOWN FILES")
    print("="*60 + "\n")
    
    # Load test markdown file from markdown output dir
    interim_dir = (project_root / config['output']['markdown_dir']).resolve()
    
    # Find the first .md file in interim folder
    md_files = list(interim_dir.rglob("*.md"))
    
    if not md_files:
        print(f"✗ No markdown files found in: {interim_dir}")
        print("\nTesting with sample data instead...\n")
        md_file = None
        
        # Sample test data
        sample_text = """# Clinical Studies

## Contraindications

Do not use in patients with [](hypersensitivity).

| Drug | Dosage |
|------|--------|
| Med-A | 5mg |
| Med-B | 10mg |

The drug showed significant improve-
ment in symptoms.


## Efficacy Results

### Phase 2 Trial
Treatment showed 50% improvement compared to placebo.

### Phase 3 Trial  
- Primary endpoint met
- Secondary endpoints pending
- Safety profile acceptable
"""
    else:
        md_file = md_files[0]
        print(f"✓ Found markdown file: {_rel(md_file)}")
        with open(md_file, 'r', encoding='utf-8') as f:
            sample_text = f.read()
    
    print("\n" + "="*60)
    print("STEP 3: TESTING TEXT CLEANER")
    print("="*60 + "\n")
    
    cleaner = TextCleaner()
    cleaned = cleaner.clean(sample_text)
    
    print(f"Original length: {len(sample_text)} characters")
    print(f"Cleaned length:  {len(cleaned)} characters")
    print(f"\nFirst 500 chars of cleaned text:")
    print("-" * 60)
    print(cleaned[:500])
    print("-" * 60)
    
    # Step 4: Save cleaned markdown to cleaned output dir
    print("\n" + "="*60)
    print("STEP 4: SAVING CLEANED MARKDOWN")
    print("="*60 + "\n")
    
    output_dir = (project_root / config['output']['cleaned_dir']).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    
    if md_file:
        cleaned_output_file = output_dir / (md_file.stem + "_cleaned.md")
    else:
        cleaned_output_file = output_dir / "sample_cleaned.md"
    
    with open(cleaned_output_file, 'w', encoding='utf-8') as f:
        f.write(cleaned)
    
    print(f"✓ Saved cleaned markdown to: {_rel(cleaned_output_file)}")
    print(f"✓ Cleaned file size: {len(cleaned)} characters\n")
    
    print("="*60)
    print("STEP 5: TESTING MARKDOWN CHUNKER")
    print("="*60 + "\n")
    
    chunker = MarkdownChunker(max_tokens=512)
    chunks = chunker.chunk(cleaned)
    
    print(f"Total chunks created: {len(chunks)}\n")
    
    # Show first 3 chunks
    for i, chunk in enumerate(chunks[:3], 1):
        print(f"--- Chunk {i} ---")
        print(f"Context: {chunk['context']}")
        print(f"Level: H{chunk['level']}")
        print(f"Content preview: {chunk['content'][:200]}...")
        print(f"Estimated tokens: {len(chunk['content']) // 4}")
        print()
    
    if len(chunks) > 3:
        print(f"... and {len(chunks) - 3} more chunks")
    
    print("\n✓ All processor tests completed!")
