"""
build_knowledge_graph.py — Stage 6: Chunks → Neo4j knowledge graph.

Thin CLI wrapper around GraphCreator (src/processors/graph_creator.py).
All extraction and Neo4j write logic lives in the processor class.

Usage:
    python scripts/build_knowledge_graph.py
    python scripts/build_knowledge_graph.py --config ../config/app.yaml
    python scripts/build_knowledge_graph.py --chunks-dir ../data/artifacts/chunk
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent  # data-ingestion/
REPO_ROOT = PROJECT_ROOT.parent

sys.path.insert(0, str(PROJECT_ROOT))

from src.config_loader import load_ingestion_config
from src.processors.graph_creator import GraphCreator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _load_config(config_path: str | None) -> dict[str, Any]:
    return load_ingestion_config(config_path or (REPO_ROOT / "config" / "app.yaml"))


def _resolve(project_root: Path, rel: str) -> Path:
    if Path(rel).is_absolute():
        return Path(rel)
    return (project_root / rel).resolve()


class KnowledgeGraphBuilder:
    """Programmatic interface to GraphCreator for use by run_pipeline.py."""

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config
        self._creator = GraphCreator(config)

    def run(self, chunks_dir: Path) -> None:
        self._creator.process_chunks_dir(Path(chunks_dir))

    def close(self) -> None:
        self._creator.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build Neo4j knowledge graph from chunk JSON files"
    )
    parser.add_argument("-c", "--config", help="Path to config YAML")
    parser.add_argument("--chunks-dir", help="Override chunks directory path")
    args = parser.parse_args()

    cfg = _load_config(args.config)

    if args.chunks_dir:
        chunks_dir = Path(args.chunks_dir).resolve()
    else:
        rel = cfg.get("output", {}).get("chunks_dir", "../data/artifacts/chunk")
        chunks_dir = _resolve(PROJECT_ROOT, rel)

    logger.info("Chunks dir: %s", chunks_dir)

    creator = GraphCreator(cfg)
    try:
        creator.process_chunks_dir(chunks_dir)
    finally:
        creator.close()
        logger.info("Done — check http://localhost:7474")


if __name__ == "__main__":
    main()
