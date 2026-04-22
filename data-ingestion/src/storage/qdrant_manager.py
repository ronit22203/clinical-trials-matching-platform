#!/usr/bin/env python3
"""
Qdrant Collection Management Tool
Manage collections in Qdrant vector database
"""

import argparse
import sys
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams
from typing import Optional, Dict, Any

from src.config_loader import load_ingestion_config


class QdrantManager:
    def __init__(self, config_path: str = None):
        """Initialize Qdrant manager with configuration"""
        self.config = self._load_config(config_path)
        self.vec_config = self.config.get('vectorization', {})
        
        qdrant_url = self.vec_config.get('qdrant_url', 'http://localhost:6333')
        self.collection_name = self.vec_config.get('collection_name', 'medical_papers')
        
        print(f"Connecting to Qdrant at {qdrant_url}...")
        self.client = QdrantClient(url=qdrant_url)
    
    def _load_config(self, config_path: str = None) -> Dict[str, Any]:
        """Load configuration from YAML file"""
        return load_ingestion_config(config_path)
    
    def list_collections(self):
        """List all collections in Qdrant"""
        try:
            collections = self.client.get_collections()
            print("Available collections:")
            for collection in collections.collections:
                print(f"  - {collection.name}")
                # Try to get collection info
                try:
                    info = self.client.get_collection(collection.name)
                    points_count = getattr(info, 'points_count', None)
                    vectors_count = getattr(info, 'vectors_count', None)
                    if points_count is not None:
                        print(f"    Points: {points_count}")
                    else:
                        print("    (Could not get points count)")
                    if vectors_count is not None:
                        print(f"    Vectors: {vectors_count}")
                    else:
                        print("    (Could not get vectors count)")
                except Exception as e:
                    print(f"    (Could not get details: {e})")
        except Exception as e:
            print(f"Error listing collections: {e}")
            return False
        return True
    
    def delete_collection(self, collection_name: str = None):
        """Delete a collection from Qdrant"""
        if collection_name is None:
            collection_name = self.collection_name
        
        try:
            if self.client.collection_exists(collection_name):
                print(f"Deleting collection: {collection_name}")
                self.client.delete_collection(collection_name)
                print(f"✓ Collection '{collection_name}' deleted successfully")
                return True
            else:
                print(f"Collection '{collection_name}' does not exist")
                return False
        except Exception as e:
            print(f"Error deleting collection: {e}")
            return False
    
    def clear_collection(self, collection_name: str = None):
        """Delete all points in a collection (keeps collection structure)"""
        if collection_name is None:
            collection_name = self.collection_name
        
        try:
            if self.client.collection_exists(collection_name):
                info = self.client.get_collection(collection_name)
                print(f"Clearing collection: {collection_name}")
                print(f"  Points to delete: {info.points_count}")
                
                # Delete all points by deleting and recreating the collection
                self.client.delete_collection(collection_name)
                print(f"✓ Collection '{collection_name}' cleared successfully")
                return True
            else:
                print(f"Collection '{collection_name}' does not exist")
                return False
        except Exception as e:
            print(f"Error clearing collection: {e}")
            return False
    
    def get_collection_stats(self, collection_name: str = None):
        """Get statistics about a collection"""
        if collection_name is None:
            collection_name = self.collection_name
        
        try:
            if self.client.collection_exists(collection_name):
                info = self.client.get_collection(collection_name)
                print(f"Collection: {collection_name}")
                print(f"  Total points: {info.points_count}")
                print(f"  Total vectors: {info.vectors_count}")
                return True
            else:
                print(f"Collection '{collection_name}' does not exist")
                return False
        except Exception as e:
            print(f"Error getting collection stats: {e}")
            return False


def main():
    parser = argparse.ArgumentParser(
        description="Manage Qdrant collections for Medical Data Ingestion",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python qdrant_manager.py list                    # List all collections
  python qdrant_manager.py stats                   # Get collection statistics
  python qdrant_manager.py clear                   # Clear all points in collection
  python qdrant_manager.py delete                  # Delete entire collection
  python qdrant_manager.py delete my_collection    # Delete specific collection
  python qdrant_manager.py -c config.yaml list    # Use custom config file
        """
    )
    
    parser.add_argument(
        'command',
        choices=['list', 'stats', 'clear', 'delete'],
        help='Command to execute'
    )
    parser.add_argument(
        'collection_name',
        nargs='?',
        help='Collection name (uses default from config if not specified)'
    )
    parser.add_argument(
        '-c', '--config',
        help='Path to config.yaml file'
    )
    
    args = parser.parse_args()
    
    try:
        manager = QdrantManager(config_path=args.config)
        
        if args.command == 'list':
            success = manager.list_collections()
        elif args.command == 'stats':
            success = manager.get_collection_stats(args.collection_name)
        elif args.command == 'clear':
            if args.collection_name is None:
                confirm = input(f"Clear all embeddings in '{manager.collection_name}'? (y/n): ")
                if confirm.lower() != 'y':
                    print("Cancelled")
                    return
            success = manager.clear_collection(args.collection_name)
        elif args.command == 'delete':
            if args.collection_name is None:
                confirm = input(f"Delete collection '{manager.collection_name}'? (y/n): ")
                if confirm.lower() != 'y':
                    print("Cancelled")
                    return
            success = manager.delete_collection(args.collection_name)
        
        sys.exit(0 if success else 1)
    
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
