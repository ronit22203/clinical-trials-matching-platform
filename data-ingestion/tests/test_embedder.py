#!/usr/bin/env python
"""
Test script for MedicalVectorizer embedder
Tests Stage 5: persisted chunks JSON -> Embed -> Qdrant.
"""
import sys
import argparse
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.storage.embedder import MedicalVectorizer, ConfigLoader

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Index one explicit persisted Stage 4 chunks artifact"
    )
    parser.add_argument("--chunks-path", help="Path to a *_chunks.json artifact")
    parser.add_argument("--scope", help="Explicit document scope")
    parser.add_argument("--collection", help="Explicit target Qdrant collection")
    args = parser.parse_args()

    print("="*60)
    print("TESTING EMBEDDER (Vectorizer)")
    print("="*60 + "\n")

    if not args.chunks_path:
        print("No --chunks-path supplied; skipping live vectorization test.")
        sys.exit(0)
    if not args.scope or not args.collection:
        parser.error("--scope and --collection are required with --chunks-path")

    try:
        # Load config
        config = ConfigLoader.load()
        print("✓ Config loaded from ../config/app.yaml")
        
        # Initialize vectorizer
        print("\nInitializing MedicalVectorizer...")
        vectorizer = MedicalVectorizer(config=config)
        
        print("✓ Embedding model initialized")
        print(f"  - Model: {config['vectorization']['model_name']}")
        print(f"  - Embedding dimension: {vectorizer.embedding_dim}")
        print(f"  - Qdrant collection: {vectorizer.collection_name}")
        
        chunks_path = Path(args.chunks_path)
        if not chunks_path.exists():
            print(f"\n✗ Chunks artifact not found: {chunks_path}")
            print("  Skipping vectorization test")
            print("\n  To run this test, you need to:")
            print("  1. Run stages 1-4 for a document")
            print("  2. Pass its exact *_chunks.json artifact with scope and collection")
        else:
            print(f"\n✓ Found chunks artifact: {chunks_path.name}")
            print("\nProcessing artifact...")
            indexed_count = vectorizer.index_chunks_path(
                chunks_path,
                scope=args.scope,
                collection_name=args.collection,
            )
            print("\n✓ Embedder test completed!")
            print(f"  Total chunks indexed: {indexed_count}")
    
    except Exception as e:
        print(f"\n✗ Error during embedder test: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
