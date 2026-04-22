#!/usr/bin/env python
"""
Test script for MedicalVectorizer embedder
Tests the full pipeline: Clean -> Chunk -> Embed -> Qdrant
"""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.storage.embedder import MedicalVectorizer, ConfigLoader

if __name__ == "__main__":
    print("="*60)
    print("TESTING EMBEDDER (Vectorizer)")
    print("="*60 + "\n")
    
    try:
        # Load config
        config = ConfigLoader.load()
        print("✓ Config loaded from ../config/app.yaml")
        
        # Initialize vectorizer
        print("\nInitializing MedicalVectorizer...")
        vectorizer = MedicalVectorizer(config=config)
        
        print(f"✓ Embedding model initialized")
        print(f"  - Model: {config['vectorization']['model_name']}")
        print(f"  - Embedding dimension: {vectorizer.embedding_dim}")
        print(f"  - Qdrant collection: {vectorizer.collection_name}")
        
        # Check if markdown files exist
        interim_dir = (project_root / config['output']['markdown_dir']).resolve()
        md_files = list(interim_dir.rglob("*.md"))
        
        if not md_files:
            print(f"\n✗ No markdown files found in {interim_dir}")
            print("  Skipping vectorization test")
            print("\n  To run this test, you need to:")
            print("  1. Extract PDFs to markdown (using pdf_marker.py)")
            print("  2. Markdown files will be in ../data/artifacts/markdown/")
        else:
            print(f"\n✓ Found {len(md_files)} markdown file(s) in {interim_dir}")
            print(f"\nProcessing files...")
            
            # Run vectorizer on markdown files
            vectorizer.run(str(interim_dir))
            
            print("\n✓ Embedder test completed!")
            print(f"  Total markdown files processed: {len(md_files)}")
    
    except Exception as e:
        print(f"\n✗ Error during embedder test: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
