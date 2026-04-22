"""
delete_knowledge_graph.py — Wipe Neo4j knowledge graph.

Reads connection settings from config/app.yaml (data_ingestion.neo4j.*) if available,
otherwise falls back to localhost defaults.

Usage:
    python scripts/delete_knowledge_graph.py
    python scripts/delete_knowledge_graph.py --config ../config/app.yaml
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent  # data-ingestion/
sys.path.insert(0, str(_PROJECT_ROOT))

from neo4j import GraphDatabase

from src.config_loader import load_ingestion_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _load_config(config_path: str | None) -> dict[str, Any]:
    return load_ingestion_config(config_path) if config_path else load_ingestion_config()



class KnowledgeGraphDeleter:
    def __init__(self, config: dict[str, Any] | None = None):
        neo4j_cfg = (config or {}).get("neo4j", {})
        self.neo4j_uri = neo4j_cfg.get("uri", "bolt://localhost:7687")
        self.neo4j_auth = (
            neo4j_cfg.get("user", "neo4j"),
            neo4j_cfg.get("password", "testpassword"),
        )
        try:
            self.driver = GraphDatabase.driver(self.neo4j_uri, auth=self.neo4j_auth)
            self.driver.verify_connectivity()
            logger.info("Connected to Neo4j at %s", self.neo4j_uri)
        except Exception as exc:
            logger.critical("Failed to connect to Neo4j: %s", exc)
            raise

    def close(self):
        self.driver.close()

    def delete_all_nodes(self):
        """Delete all nodes and relationships from the graph."""
        with self.driver.session() as session:
            try:
                # First, delete all relationships
                session.run("MATCH ()-[r]-() DELETE r")
                logger.info("Deleted all relationships")
                
                # Then, delete all nodes
                session.run("MATCH (n) DELETE n")
                logger.info("Deleted all nodes")
                
                # Verify the graph is empty
                result = session.run("MATCH (n) RETURN COUNT(n) as count")
                count = result.single()['count']
                
                if count == 0:
                    logger.info("✓ Graph successfully cleared - 0 nodes remaining")
                else:
                    logger.warning(f"Graph still contains {count} nodes")
                    
            except Exception as e:
                logger.error(f"Failed to delete graph: {e}")
                raise e

    def delete_entities_by_source(self, source_pattern: str):
        """Delete entities/relationships by source file pattern."""
        with self.driver.session() as session:
            try:
                # Delete relationships with matching source
                result = session.run(
                    "MATCH ()-[r {source: $pattern}]-() DELETE r RETURN count(r) as count",
                    pattern=source_pattern
                )
                deleted_rels = result.single()['count']
                logger.info(f"Deleted {deleted_rels} relationships from source: {source_pattern}")
                
                # Clean up orphaned nodes (nodes with no relationships)
                result = session.run("MATCH (n) WHERE NOT (n)--() DELETE n RETURN count(n) as count")
                deleted_nodes = result.single()['count']
                logger.info(f"Cleaned up {deleted_nodes} orphaned nodes")
                
            except Exception as e:
                logger.error(f"Failed to delete by source: {e}")
                raise e

    def get_graph_stats(self):
        """Get statistics about the current graph."""
        with self.driver.session() as session:
            try:
                node_count = session.run("MATCH (n) RETURN COUNT(n) as count").single()['count']
                rel_count = session.run("MATCH ()-[r]-() RETURN COUNT(r) as count").single()['count']
                
                logger.info(f"Graph Stats: {node_count} nodes, {rel_count} relationships")
                return {"nodes": node_count, "relationships": rel_count}
                
            except Exception as e:
                logger.error(f"Failed to get graph stats: {e}")
                return None

    def run(self):
        """Main execution."""
        logger.info("Starting Knowledge Graph Deletion...")
        
        # Show current stats
        stats = self.get_graph_stats()
        
        if stats and stats['nodes'] == 0:
            logger.info("Graph is already empty")
            return
        
        # Delete all nodes and relationships
        self.delete_all_nodes()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Delete Neo4j knowledge graph")
    parser.add_argument("-c", "--config", help="Path to config YAML")
    args = parser.parse_args()

    cfg = _load_config(args.config)
    deleter = KnowledgeGraphDeleter(cfg)
    try:
        deleter.run()
    finally:
        deleter.close()
        logger.info("Done")
