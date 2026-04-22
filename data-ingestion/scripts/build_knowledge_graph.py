"""
build_knowledge_graph.py — Stage 6: Chunks → Neo4j knowledge graph.

Reads chunk JSON files produced by Stage 4, sends each chunk to a local Ollama
LLM (default: biomistral for medical domain) to extract (head, relation, tail)
triplets, then writes them to Neo4j as typed relationships.

All settings come from config/app.yaml (data_ingestion.neo4j.* and data_ingestion.knowledge_graph.*).

Usage:
    python scripts/build_knowledge_graph.py                           # uses default config
    python scripts/build_knowledge_graph.py --config ../config/app.yaml
    python scripts/build_knowledge_graph.py --chunks-dir ../data/artifacts/chunks
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent  # data-ingestion/
REPO_ROOT = PROJECT_ROOT.parent

sys.path.insert(0, str(PROJECT_ROOT))

import requests
from neo4j import GraphDatabase

from src.config_loader import load_ingestion_config

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
    def __init__(self, config: dict[str, Any]):
        neo4j_cfg = config.get("neo4j", {})
        kg_cfg = config.get("knowledge_graph", {})

        self.neo4j_uri = neo4j_cfg.get("uri", "bolt://localhost:7687")
        self.neo4j_auth = (
            neo4j_cfg.get("user", "neo4j"),
            neo4j_cfg.get("password", "testpassword"),
        )

        self.ollama_url = kg_cfg.get("ollama_url", "http://localhost:11434/api/generate")
        self.model = kg_cfg.get("model", "cniongolo/biomistral:latest")
        self.max_retries = kg_cfg.get("max_retries", 2)
        self.timeout = kg_cfg.get("timeout_seconds", 120)
        self.max_chars = kg_cfg.get("max_text_chars", 2000)
        self.min_chars = kg_cfg.get("min_chunk_chars", 50)

        try:
            self.driver = GraphDatabase.driver(self.neo4j_uri, auth=self.neo4j_auth)
            self.driver.verify_connectivity()
            logger.info("Connected to Neo4j at %s", self.neo4j_uri)
        except Exception as exc:
            logger.critical("Failed to connect to Neo4j: %s", exc)
            raise

    def close(self) -> None:
        self.driver.close()

    # ── LLM extraction ────────────────────────────────────────────────────────

    def extract_relations(self, text: str) -> list[dict]:
        if len(text) < self.min_chars:
            return []

        prompt = (
            "<s>[INST] You are a medical knowledge graph extractor. "
            "Analyze the text and extract triplets: (Head, Relation, Tail).\n\n"
            "Rules:\n"
            "1. Return ONLY a valid JSON object.\n"
            "2. 'head' and 'tail' must be specific medical entities (Drugs, Diseases, Symptoms, Genes).\n"
            "3. 'relation' must be a single verb in UPPERCASE (e.g., TREATS, CAUSES, PREVENTS, INHIBITS).\n"
            "4. Do not output conversational text.\n\n"
            f'Text: "{text[:self.max_chars]}"\n\n'
            "Expected JSON Structure:\n"
            '{"triplets": [{"head": "Aspirin", "relation": "TREATS", "tail": "Headache"}]} [/INST]'
        )

        for attempt in range(self.max_retries):
            try:
                resp = requests.post(
                    self.ollama_url,
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                        "format": "json",
                        "options": {"temperature": 0.0, "num_ctx": 4096},
                    },
                    timeout=self.timeout,
                )
                if resp.status_code != 200:
                    logger.warning("Ollama HTTP %s (attempt %d)", resp.status_code, attempt + 1)
                    time.sleep(2 ** attempt)
                    continue

                raw = resp.json().get("response", "{}")
                parsed = json.loads(raw)
                triplets = parsed.get("triplets", []) or parsed.get("relations", [])
                valid = [t for t in triplets if {"head", "relation", "tail"} <= t.keys()]
                logger.debug("Extracted %d triplets", len(valid))
                return valid

            except json.JSONDecodeError:
                logger.warning("JSON parse error (attempt %d)", attempt + 1)
            except requests.exceptions.Timeout:
                logger.warning("Ollama timeout (attempt %d/%d)", attempt + 1, self.max_retries)
            except requests.exceptions.ConnectionError:
                logger.warning("Ollama connection error (attempt %d/%d)", attempt + 1, self.max_retries)
            except Exception as exc:
                logger.error("Extraction error: %s", exc)

            if attempt < self.max_retries - 1:
                time.sleep(2 ** attempt)

        return []

    # ── Neo4j write ───────────────────────────────────────────────────────────

    def ingest_triplets(self, triplets: list[dict], source_file: str, chunk_id: int) -> None:
        if not triplets:
            return

        with self.driver.session() as session:
            for t in triplets:
                head = t["head"].strip().upper()
                tail = t["tail"].strip().upper()
                raw_rel = t["relation"].strip().upper().replace(" ", "_").replace("-", "_")
                relation_type = "".join(c for c in raw_rel if c.isalnum() or c == "_") or "RELATED_TO"

                # Relationship TYPE cannot be parameterized in Cypher — sanitized above.
                query = f"""
                MERGE (h:Entity {{name: $head}})
                MERGE (t:Entity {{name: $tail}})
                MERGE (h)-[r:{relation_type}]->(t)
                SET r.source = $source, r.chunk_id = $chunk_id
                """
                try:
                    session.run(query, head=head, tail=tail,
                                source=source_file, chunk_id=chunk_id)
                except Exception as exc:
                    logger.warning("Neo4j write error: %s", exc)

        logger.info("  → graph: +%d relations from %s chunk %d",
                    len(triplets), source_file, chunk_id)

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self, chunks_dir: Path) -> int:
        """Process all chunk JSON files in chunks_dir. Returns count of files processed."""
        chunk_files = sorted(chunks_dir.glob("*_chunks.json"))
        if not chunk_files:
            logger.warning("No *_chunks.json files found in %s", chunks_dir)
            return 0

        logger.info("Found %d chunk file(s) to process", len(chunk_files))
        total_relations = 0

        for file_path in chunk_files:
            logger.info("Processing: %s", file_path.name)
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)

            chunks = data.get("chunks", []) if isinstance(data, dict) else data

            for i, chunk in enumerate(chunks):
                content = chunk.get("content", "")
                if len(content) < self.min_chars:
                    continue
                try:
                    logger.info("  Chunk %d/%d — extracting relations…", i + 1, len(chunks))
                    triplets = self.extract_relations(content)
                    self.ingest_triplets(triplets, file_path.stem, i)
                    total_relations += len(triplets)
                except KeyboardInterrupt:
                    logger.info("Interrupted at chunk %d. Run again to resume.", i + 1)
                    raise
                except Exception as exc:
                    logger.error("Error on chunk %d: %s", i + 1, exc)

        logger.info("Knowledge graph build complete — %d total relations written", total_relations)
        return len(chunk_files)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Neo4j knowledge graph from chunk JSON files")
    parser.add_argument("-c", "--config", help="Path to config YAML (default: ../config/app.yaml)")
    parser.add_argument("--chunks-dir", help="Override chunks directory path")
    args = parser.parse_args()

    cfg = _load_config(args.config)

    if args.chunks_dir:
        chunks_dir = Path(args.chunks_dir).resolve()
    else:
        rel = cfg.get("output", {}).get("chunks_dir", "data/chunks")
        chunks_dir = _resolve(PROJECT_ROOT, rel)

    logger.info("Chunks dir: %s", chunks_dir)

    builder = KnowledgeGraphBuilder(cfg)
    try:
        builder.run(chunks_dir)
    finally:
        builder.close()
        logger.info("Done — check http://localhost:7474")


if __name__ == "__main__":
    main()
