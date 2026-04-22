#!/usr/bin/env python
"""
Test script for Qdrant Collection Management
Tests QdrantManager capabilities: list, stats, clear, delete
"""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.storage.qdrant_manager import QdrantManager

if __name__ == "__main__":
    print("="*60)
    print("TESTING QDRANT CLIENT (Collection Manager)")
    print("="*60 + "\n")
    
    try:
        # Initialize manager with default config
        print("Connecting to Qdrant...")
        manager = QdrantManager(config_path=str(project_root.parent / "config" / "app.yaml"))
        
        print("\n1. Listing all collections:")
        print("-" * 60)
        manager.list_collections()
        
        print("\n2. Getting collection statistics:")
        print("-" * 60)
        manager.get_collection_stats()
        
        print("\n✓ Qdrant client test completed!")
        print("\nAvailable commands:")
        print("  python -m src.storage.qdrant_client list      # List all collections")
        print("  python -m src.storage.qdrant_client stats     # Get collection stats")
        print("  python -m src.storage.qdrant_client clear     # Clear collection (interactive)")
        print("  python -m src.storage.qdrant_client delete    # Delete collection (interactive)")
        
    except Exception as e:
        print(f"\n✗ Error during Qdrant test: {e}")
        print("\nMake sure Qdrant is running:")
        print("  docker-compose -f infra/docker-compose.yaml up -d")
        import traceback
        traceback.print_exc()
        sys.exit(1)
