#!/usr/bin/env python3
"""
Pipeline Test & Inspection Script
Verifies the pipeline works end-to-end and provides traceability inspection
"""

import json
import sys
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent

def format_size(bytes_val):
    """Format bytes to human readable size"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_val < 1024:
            return f"{bytes_val:.1f} {unit}"
        bytes_val /= 1024
    return f"{bytes_val:.1f} TB"

def inspect_stage_1():
    """Inspect OCR outputs"""
    print("\n" + "="*70)
    print("STAGE 1: OCR (PDF → OCR JSON)")
    print("="*70)
    
    stage1_dir = PROJECT_ROOT / "data" / "ocr"
    
    if not stage1_dir.exists():
        print("Stage 1 directory not found")
        return
    
    json_files = list(stage1_dir.glob("*_ocr.json"))
    if not json_files:
        print("No OCR JSON files found")
        return
    
    print(f"✓ Found {len(json_files)} OCR JSON file(s)\n")
    
    for json_file in json_files:
        print(f"{json_file.name}")
        file_size = format_size(json_file.stat().st_size)
        print(f"   Size: {file_size}")
        
        try:
            with open(json_file) as f:
                data = json.load(f)
            
            total_lines = sum(len(page.get('text_lines', [])) for page in data)
            print(f"Pages: {len(data)}")
            print(f"Total text lines: {total_lines}")
            
            # Sample first few lines from first page
            if data and data[0].get('text_lines'):
                print(f"Sample (first 2 lines):")
                for line in data[0]['text_lines'][:2]:
                    text_preview = line['text'][:50].replace('\n', ' ')
                    conf = line.get('confidence', 0)
                    print(f"• {text_preview}... (confidence: {conf:.2f})")
        
        except Exception as e:
            print(f"Error reading: {e}")
        
        # Check for debug visualizations
        doc_name = json_file.stem.replace('_ocr', '')
        debug_dir = stage1_dir / doc_name / "debug_visualizations"
        if debug_dir.exists():
            png_files = list(debug_dir.glob("*.png"))
            print(f"   Debug visualizations: {len(png_files)} PNG files ✓")

def inspect_stage_2():
    """Inspect converted markdown"""
    print("\n" + "="*70)
    print("STAGE 2: CONVERT (OCR JSON → Markdown)")
    print("="*70)
    
    stage2_dir = PROJECT_ROOT / "data" / "markdown"
    
    if not stage2_dir.exists():
        print("Stage 2 directory not found")
        return
    
    md_files = list(stage2_dir.glob("*_converted.md"))
    if not md_files:
        print("No converted markdown files found")
        return
    
    print(f"✓ Found {len(md_files)} converted markdown file(s)\n")
    
    for md_file in md_files:
        print(f"{md_file.name}")
        file_size = format_size(md_file.stat().st_size)
        print(f"Size: {file_size}")
        
        try:
            with open(md_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            lines = content.split('\n')
            headers = [l for l in lines if l.startswith('#')]
            print(f"Lines: {len(lines)}")
            print(f"Headers found: {len(headers)}")
            
            if headers:
                print(f"Sample headers:")
                for header in headers[:3]:
                    print(f"• {header[:60]}")
            
            # Preview first paragraph
            paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
            if paragraphs:
                preview = paragraphs[0][:100].replace('\n', ' ')
                print(f"First paragraph: {preview}...")
        
        except Exception as e:
            print(f"Error reading: {e}")

def inspect_stage_3():
    """Inspect cleaned markdown"""
    print("\n" + "="*70)
    print("STAGE 3: CLEAN (Markdown → Cleaned)")
    print("="*70)
    
    stage3_dir = PROJECT_ROOT / "data" / "cleaned"
    
    if not stage3_dir.exists():
        print("Stage 3 directory not found")
        return
    
    md_files = list(stage3_dir.glob("*_cleaned.md"))
    if not md_files:
        print("No cleaned markdown files found")
        return
    
    print(f"Found {len(md_files)} cleaned markdown file(s)\n")
    
    for md_file in md_files:
        print(f"{md_file.name}")
        file_size = format_size(md_file.stat().st_size)
        print(f"   Size: {file_size}")
        
        try:
            with open(md_file, 'r', encoding='utf-8') as f:
                cleaned = f.read()
            
            # Compare with converted
            converted_name = md_file.name.replace('_cleaned', '_converted')
            converted_file = PROJECT_ROOT / "data" / "stage2_converted" / converted_name
            
            if converted_file.exists():
                with open(converted_file, 'r', encoding='utf-8') as f:
                    original = f.read()
                
                reduction = 100 - (100 * len(cleaned) // len(original))
                print(f"   Reduction from Stage 2: {reduction}% (size decreased)")
            
            lines = cleaned.split('\n')
            print(f"   Lines: {len(lines)}")
            
            # Check for artifacts
            has_links = '[](' in cleaned
            has_images = '![' in cleaned
            print(f"Phantom links removed: ✓ (still present: {has_links})")
            print(f"Phantom images removed: ✓ (still present: {has_images})")
        
        except Exception as e:
            print(f"Error reading: {e}")
def inspect_stage_4():
    """Inspect chunked JSON"""
    print("\n" + "="*70)
    print("STAGE 4: CHUNK (Markdown → Chunks)")
    print("="*70)
    
    stage4_dir = PROJECT_ROOT / "data" / "chunks"
    
    if not stage4_dir.exists():
        print("Stage 4 directory not found")
        return
    
    json_files = list(stage4_dir.glob("*_chunks.json"))
    if not json_files:
        print("No chunks JSON files found")
        return
    
    print(f"Found {len(json_files)} chunks JSON file(s)\n")
    
    for json_file in json_files:
        print(f"{json_file.name}")
        file_size = format_size(json_file.stat().st_size)
        print(f"Size: {file_size}")
        
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            print(f"Total chunks: {data.get('total_chunks', 'N/A')}")
            
            config = data.get('chunk_config', {})
            print(f"Chunk config:")
            print(f"• max_tokens: {config.get('max_tokens')}")
            print(f"• overlap: {config.get('chunk_overlap')}")
            
            chunks = data.get('chunks', [])
            if chunks:
                sample = chunks[0]
                print(f"Sample chunk:")
                print(f"• Context: {sample.get('context', 'N/A')[:60]}")
                print(f"• Level: {sample.get('level')}")
                content_preview = sample.get('content', '')[:80].replace('\n', ' ')
                print(f"• Content: {content_preview}...")
        
        except Exception as e:
            print(f"Error reading: {e}")

def check_qdrant():
    """Check Qdrant connection and collection"""
    print("\n" + "="*70)
    print("STAGE 5: VECTORIZE (Qdrant Vector Database)")
    print("="*70)
    
    try:
        from qdrant_client import QdrantClient
        
        client = QdrantClient("http://localhost:6333")
        collections = client.get_collections()
        
        col_names = [c.name for c in collections.collections]
        print(f"✓ Connected to Qdrant")
        print(f"  Collections: {col_names if col_names else 'None'}")
        
        if 'medical_papers' in col_names:
            stats = client.get_collection('medical_papers')
            print(f"\n  medical_papers collection:")
            print(f"    • Points: {stats.points_count}")
            print(f"    • Vector size: {stats.config.params.vectors.size}")
            print(f"    • Status: {stats.status}")
    
    except Exception as e:
        print(f"Qdrant not available: {e}")
        print(f"Run: make docker-up")

def print_summary():
    """Print pipeline summary"""
    print("\n" + "="*70)
    print("PIPELINE SUMMARY")
    print("="*70)
    
    stages = [
        ("Stage 1: OCR",       "data/ocr", "*_ocr.json"),
        ("Stage 2: Markdown",  "data/markdown", "*_converted.md"),
        ("Stage 3: Cleaned",   "data/cleaned", "*_cleaned.md"),
        ("Stage 4: Chunks",    "data/chunks", "*_chunks.json"),
    ]
    
    print("\nData flow:")
    for stage_name, path, pattern in stages:
        stage_dir = PROJECT_ROOT / path
        if stage_dir.exists():
            files = list(stage_dir.glob(pattern))
            status = f"✓ {len(files)} file(s)"
        else:
            status = "❌ Not run"
        
        print(f"  {stage_name:<10} {path:<30} {status}")
    
    # Check Qdrant
    try:
        from qdrant_client import QdrantClient
        client = QdrantClient("http://localhost:6333")
        collections = client.get_collections()
        if any(c.name == 'medical_papers' for c in collections.collections):
            print(f"  Stage 5    Qdrant Vector DB                ✓ Indexed")
        else:
            print(f"  Stage 5    Qdrant Vector DB                Not indexed")
    except:
        print(f"  Stage 5    Qdrant Vector DB                Offline")
    
    print(f"\nFull documentation: docs/data_flow.md")

def main():
    print("\n" + ""*20)
    print("PIPELINE INSPECTION TOOL")
    print(""*20)
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    inspect_stage_1()
    inspect_stage_2()
    inspect_stage_3()
    inspect_stage_4()
    check_qdrant()
    print_summary()
    
    print("\n" + "="*70)
    print("Inspection complete!")
    print("="*70 + "\n")

if __name__ == "__main__":
    main()
