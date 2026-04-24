"""
extraction_evaluator.py — Entity/relation F1 against Neo4j knowledge graph.

Compares the KG extracted from the sepsis paper against hand-annotated golden files.

Matching modes:
  - Entity exact:   case-insensitive name match (Neo4j stores UPPERCASE)
  - Entity relaxed: substring or fuzzy match (threshold 0.8 token-sort ratio)
  - Relation strict:  exact (head, type, tail) triple match (all case-insensitive)
  - Relation relaxed: (head, tail) match only — type ignored

Usage:
    python evaluators/extraction_evaluator.py \\
        --golden-entities golden/sepsis_entities.json \\
        --golden-relations golden/sepsis_relationships.json \\
        --output results/<RUN_DIR>/extraction.json \\
        [--source-filter 2026.03.17.26348414]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RUN_ID_ENV = "BENCH_RUN_ID"


# ---------------------------------------------------------------------------
# String normalization
# ---------------------------------------------------------------------------

def _norm(s: str) -> str:
    """Lowercase, collapse whitespace, strip punctuation noise."""
    return re.sub(r"\s+", " ", s.lower().strip().rstrip("."))


def _token_sort(a: str, b: str) -> float:
    """Simple token-sort Jaccard similarity for relaxed matching."""
    ta = set(_norm(a).split())
    tb = set(_norm(b).split())
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _entity_matches(predicted: str, golden: str, relaxed: bool = False) -> bool:
    pn, gn = _norm(predicted), _norm(golden)
    if pn == gn:
        return True
    if relaxed:
        # substring match
        if pn in gn or gn in pn:
            return True
        # token-sort Jaccard >= 0.5 (lenient — many entities are multi-word)
        if _token_sort(pn, gn) >= 0.5:
            return True
    return False


# ---------------------------------------------------------------------------
# Micro-averaged F1
# ---------------------------------------------------------------------------

def _prf(tp: int, predicted: int, golden: int) -> dict[str, float]:
    precision = tp / predicted if predicted > 0 else 0.0
    recall = tp / golden if golden > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    return {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4)}


# ---------------------------------------------------------------------------
# Neo4j querier
# ---------------------------------------------------------------------------

def _load_env() -> dict[str, str]:
    env_file = _REPO_ROOT / ".env.local"
    env: dict[str, str] = {}
    if not env_file.exists():
        return env
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _resolve_env_str(val: str, env: dict[str, str]) -> str:
    return re.sub(r"\$\{([^}]+)\}", lambda m: env.get(m.group(1), ""), val)


def _fetch_graph(
    neo4j_uri: str,
    neo4j_user: str,
    neo4j_password: str,
    neo4j_database: str,
    source_filter: str,
) -> tuple[list[str], list[tuple[str, str, str]]]:
    """
    Returns:
        entities: list of unique entity names
        relations: list of (head, relation_type, tail) tuples

    When the source filter matches nothing, logs the actual ``r.source`` values
    present in the graph so the caller can diagnose slug/naming mismatches.
    """
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
    try:
        with driver.session(database=neo4j_database) as session:
            cypher = """
                MATCH (h:Entity)-[r]->(t:Entity)
                WHERE r.source CONTAINS $source
                RETURN h.name AS head, type(r) AS rel_type, t.name AS tail
            """
            records = list(session.run(cypher, source=source_filter))

            # Diagnostic fallback: if the filter matched nothing, surface what
            # r.source values *do* exist so the caller can spot slug mismatches.
            if not records:
                diag = list(session.run(
                    "MATCH ()-[r]->() WHERE r.source IS NOT NULL "
                    "RETURN DISTINCT r.source AS src LIMIT 20"
                ))
                actual_sources = [d["src"] for d in diag]
                if actual_sources:
                    log.warning(
                        "Source filter '%s' matched 0 relationships. "
                        "Actual r.source values in graph: %s. "
                        "Re-ingest after fixing the slug to align these.",
                        source_filter,
                        actual_sources,
                    )
                else:
                    log.warning(
                        "Source filter '%s' matched 0 relationships and the graph "
                        "appears empty. Verify Neo4j is populated before evaluating.",
                        source_filter,
                    )
    finally:
        driver.close()

    entities_set: set[str] = set()
    relations: list[tuple[str, str, str]] = []
    for rec in records:
        head = rec["head"] or ""
        tail = rec["tail"] or ""
        rel_type = rec["rel_type"] or ""
        entities_set.add(head)
        entities_set.add(tail)
        relations.append((head, rel_type, tail))

    return list(entities_set), relations


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------

class ExtractionEvaluator:
    def __init__(
        self,
        neo4j_uri: str,
        neo4j_user: str,
        neo4j_password: str,
        neo4j_database: str = "neo4j",
        source_filter: str = "2026.03.17.26348414",
    ) -> None:
        self.neo4j_uri = neo4j_uri
        self.neo4j_user = neo4j_user
        self.neo4j_password = neo4j_password
        self.neo4j_database = neo4j_database
        self.source_filter = source_filter

    def evaluate_entities(
        self,
        predicted: list[str],
        golden: list[str],
    ) -> dict[str, Any]:
        # Exact match (case-insensitive)
        exact_tp = sum(
            1 for g in golden
            if any(_entity_matches(p, g, relaxed=False) for p in predicted)
        )
        exact = _prf(exact_tp, len(predicted), len(golden))

        # Relaxed match
        relaxed_tp = sum(
            1 for g in golden
            if any(_entity_matches(p, g, relaxed=True) for p in predicted)
        )
        relaxed = _prf(relaxed_tp, len(predicted), len(golden))

        # Per-entity detail (relaxed)
        matched = []
        missed = []
        for g in golden:
            candidates = [p for p in predicted if _entity_matches(p, g, relaxed=True)]
            if candidates:
                matched.append({"golden": g, "matched_predicted": candidates[0]})
            else:
                missed.append(g)

        return {
            "exact": exact,
            "relaxed": relaxed,
            "matched_count": len(matched),
            "missed_count": len(missed),
            "missed": missed,
        }

    def evaluate_relations(
        self,
        predicted: list[tuple[str, str, str]],
        golden: list[tuple[str, str, str]],
    ) -> dict[str, Any]:
        # Strict: exact (head, type, tail) case-insensitive
        def strict_match(p: tuple[str, str, str], g: tuple[str, str, str]) -> bool:
            return (
                _norm(p[0]) == _norm(g[0])
                and _norm(p[1]) == _norm(g[1])
                and _norm(p[2]) == _norm(g[2])
            )

        # Relaxed: (head, tail) fuzzy match, type ignored
        def relaxed_match(p: tuple[str, str, str], g: tuple[str, str, str]) -> bool:
            head_ok = _entity_matches(p[0], g[0], relaxed=True)
            tail_ok = _entity_matches(p[2], g[2], relaxed=True)
            return head_ok and tail_ok

        strict_tp = sum(
            1 for g in golden
            if any(strict_match(p, g) for p in predicted)
        )
        relaxed_tp = sum(
            1 for g in golden
            if any(relaxed_match(p, g) for p in predicted)
        )

        missed_strict = [
            {"source": g[0], "type": g[1], "target": g[2]}
            for g in golden
            if not any(strict_match(p, g) for p in predicted)
        ]
        missed_relaxed = [
            {"source": g[0], "type": g[1], "target": g[2]}
            for g in golden
            if not any(relaxed_match(p, g) for p in predicted)
        ]

        return {
            "strict": _prf(strict_tp, len(predicted), len(golden)),
            "relaxed": _prf(relaxed_tp, len(predicted), len(golden)),
            "missed_strict": missed_strict,
            "missed_relaxed": missed_relaxed,
        }

    def run(
        self,
        golden_entities_path: Path,
        golden_relations_path: Path,
        output_path: Path,
        run_id: str,
    ) -> dict[str, Any]:
        with open(golden_entities_path) as f:
            ge_data = json.load(f)
        with open(golden_relations_path) as f:
            gr_data = json.load(f)

        golden_entities = [e["name"] for e in ge_data["entities"]]
        golden_relations: list[tuple[str, str, str]] = [
            (r["source"], r["type"], r["target"])
            for r in gr_data["relationships"]
        ]

        log.info("Connecting to Neo4j at %s …", self.neo4j_uri)
        log.info("Source filter: '%s'", self.source_filter)

        predicted_entities, predicted_relations_raw = _fetch_graph(
            self.neo4j_uri,
            self.neo4j_user,
            self.neo4j_password,
            self.neo4j_database,
            self.source_filter,
        )

        log.info(
            "Predicted: %d entities, %d relations",
            len(predicted_entities),
            len(predicted_relations_raw),
        )
        log.info(
            "Golden: %d entities, %d relations",
            len(golden_entities),
            len(golden_relations),
        )

        entity_result = self.evaluate_entities(predicted_entities, golden_entities)
        relation_result = self.evaluate_relations(predicted_relations_raw, golden_relations)

        result: dict[str, Any] = {
            "run_id": run_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source_filter": self.source_filter,
            "predicted_entity_count": len(predicted_entities),
            "golden_entity_count": len(golden_entities),
            "predicted_relation_count": len(predicted_relations_raw),
            "golden_relation_count": len(golden_relations),
            "entity_metrics": entity_result,
            "relation_metrics": relation_result,
            "predicted_entities_sample": sorted(predicted_entities)[:30],
            "predicted_relations_sample": [
                {"head": h, "type": t, "tail": tl}
                for h, t, tl in predicted_relations_raw[:20]
            ],
        }

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(result, f, indent=2)

        log.info("Extraction results written → %s", output_path)
        _print_summary(entity_result, relation_result, len(predicted_entities), len(predicted_relations_raw))
        return result


def _print_summary(
    entity_result: dict[str, Any],
    relation_result: dict[str, Any],
    n_pred_entities: int,
    n_pred_relations: int,
) -> None:
    print("\n── Extraction Summary ───────────────────────────────")
    print(f"  Predicted entities:  {n_pred_entities}")
    print(f"  Predicted relations: {n_pred_relations}")
    ee = entity_result["exact"]
    er = entity_result["relaxed"]
    rs = relation_result["strict"]
    rr = relation_result["relaxed"]
    print(f"\n  Entity   (exact)   P={ee['precision']:.3f}  R={ee['recall']:.3f}  F1={ee['f1']:.3f}")
    print(f"  Entity   (relaxed) P={er['precision']:.3f}  R={er['recall']:.3f}  F1={er['f1']:.3f}")
    print(f"  Relation (strict)  P={rs['precision']:.3f}  R={rs['recall']:.3f}  F1={rs['f1']:.3f}")
    print(f"  Relation (relaxed) P={rr['precision']:.3f}  R={rr['recall']:.3f}  F1={rr['f1']:.3f}")
    missed = entity_result["missed"]
    if missed:
        print(f"\n  Missed entities ({len(missed)}): {', '.join(missed[:8])}" +
              (" …" if len(missed) > 8 else ""))
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Extraction evaluator: entity/relation F1 vs Neo4j")
    p.add_argument("--golden-entities", required=True)
    p.add_argument("--golden-relations", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--run-id", default=os.environ.get(_RUN_ID_ENV, f"bench_{int(time.time())}"))
    p.add_argument("--neo4j-uri", default=None)
    p.add_argument("--neo4j-user", default=None)
    p.add_argument("--neo4j-password", default=None)
    p.add_argument("--neo4j-database", default="neo4j")
    p.add_argument("--source-filter", default="2026.03.17.26348414")
    return p


def main() -> None:
    import yaml

    args = _build_parser().parse_args()

    env = _load_env()
    cfg_path = _REPO_ROOT / "config" / "app.yaml"
    with open(cfg_path) as f:
        app_cfg: dict[str, Any] = yaml.safe_load(f) or {}

    def _resolve(val: str) -> str:
        return _resolve_env_str(val, env)

    ingestion_neo4j = app_cfg.get("data_ingestion", {}).get("neo4j", {})
    services_neo4j = app_cfg.get("services", {}).get("neo4j", {})

    default_uri = _resolve(ingestion_neo4j.get("uri", services_neo4j.get("uri", "bolt://localhost:7687")))
    default_user = _resolve(ingestion_neo4j.get("user", services_neo4j.get("user", "neo4j")))
    default_password = _resolve(ingestion_neo4j.get("password", env.get("NEO4J_PASSWORD", "neo4j")))
    default_db = ingestion_neo4j.get("database", services_neo4j.get("database", "neo4j"))

    evaluator = ExtractionEvaluator(
        neo4j_uri=args.neo4j_uri or default_uri,
        neo4j_user=args.neo4j_user or default_user,
        neo4j_password=args.neo4j_password or default_password,
        neo4j_database=args.neo4j_database or default_db,
        source_filter=args.source_filter,
    )
    evaluator.run(
        golden_entities_path=Path(args.golden_entities),
        golden_relations_path=Path(args.golden_relations),
        output_path=Path(args.output),
        run_id=args.run_id,
    )


if __name__ == "__main__":
    main()
