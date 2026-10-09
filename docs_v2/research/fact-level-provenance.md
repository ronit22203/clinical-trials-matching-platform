# KG Hardening Plan: Provenance, Entity Resolution, Resume

## Problem

The current KG implementation lacks:

1. **Byte-range provenance** — no way to point a clinician to the exact sentence backing a claim
2. **Entity deduplication** — "TYPE 2 DIABETES" and "TYPE2 DIABETES" are separate nodes
3. **Configurable graph retrieval limit** — `LIMIT 5` is hardcoded in `HybridRetriever`
4. **Chunk-level resume** — a crash at chunk 47/200 restarts from 0

---

## Approach

Four surgical changes across three files + config. No pipeline restructure needed.

---

## Todos

### T1 — Byte-range tracking in `MarkdownChunker`

**File:** `data-ingestion/src/processors/chunker.py`

The chunker parses `text.split('\n')`. Add a precomputed `line_offsets` list mapping each line index → its character start position in the original text. Thread `char_start` / `char_end` through every code path that produces a chunk dict.

**Changes:**

- `_parse_sections()`: maintain `char_cursor` as lines are consumed; record `char_start` (offset of first content line) and `char_end` (offset after last content line) on each section dict
- `_create_section()`: accept and store `char_start`, `char_end`
- `_split_large_section()`: compute sub-chunk char_start/char_end by scanning paragraph positions relative to `section['char_start']` within the original section content string
- Every dict returned from `chunk()` gains two new fields: `char_start: int`, `char_end: int`

Backward compat: these fields simply don't exist in old JSON files — `process_chunks_dir` defaults to `None`.

---

### T2 — Tier extraction + byte-range write in `GraphCreator`

**Files:** `data-ingestion/src/processors/graph_creator.py`, `config/app.yaml`

**Prompt change:**
Add `tier` (int 1/2/3) to every triplet in the response schema:

- 1 = literal (words appear verbatim in text)
- 2 = stated (clearly expressed, paraphrased)
- 3 = inferred (logical deduction not directly stated)

Update `_RESPONSE_SCHEMA`, `_PROMPT_BASE`, and the three `few_shot_examples` in `app.yaml`.

**`write_triplets()` signature change:**

```python
def write_triplets(self, triplets, source_file, chunk_id,
                   byte_start=None, byte_end=None) -> None:
```

Add to Cypher SET:

```
SET r.source = $source, r.chunk_id = $chunk_id,
    r.byte_start = $byte_start, r.byte_end = $byte_end,
    r.tier = $tier
```

`tier` comes from each triplet dict (default 2 if absent).

**`process_chunks_dir()` change:**
Read `chunk.get("char_start")` and `chunk.get("char_end")` and forward them to `write_triplets`.

---

### T3 — Entity normalization in `GraphCreator`

**File:** `data-ingestion/src/processors/graph_creator.py`

Add a module-level `_normalize_entity()` function:

```python
def _normalize_entity(name: str) -> str:
    name = name.upper().strip()
    name = re.sub(r'\bTYPE\s+(\d+)\b', r'TYPE\1', name)   # TYPE 2 → TYPE2
    name = re.sub(r'\bCOVID[\s-]*19\b', 'COVID19', name)   # COVID-19 variants
    name = re.sub(r'\s+', ' ', name)                        # collapse spaces
    name = name.strip('.,;:')                               # strip trailing punctuation
    return name
```

Replace the two `.strip().upper()` calls in `write_triplets()` with `_normalize_entity()`.

---

### T4 — Configurable `graph_facts_limit` in `HybridRetriever`

**Files:** `config/app.yaml`, `data-ingestion/src/retrieval/hybrid.py`

Config change — add under `data_ingestion.retrieval`:

```yaml
graph_facts_limit: 10
```

Code change in `__init__`:

```python
self._graph_facts_limit: int = retrieval_cfg.get('graph_facts_limit', 5)
```

Replace `LIMIT 5` in `_fetch_graph_context` Cypher with `$limit` param.

---

### T5 — Chunk-level resume in `GraphCreator`

**File:** `data-ingestion/src/processors/graph_creator.py`

Write a `.kg_progress.json` file alongside the chunks dir:

```json
{ "nihms-2137905_cleaned_chunks": [0, 1, 2, 5], ... }
```

In `process_chunks_dir()`:

- Load progress file at start (missing file → empty dict)
- Before each `extract_triplets` call: skip if `(file_stem, chunk_idx)` already in progress
- After each successful `write_triplets`: append to progress and flush to disk

Log a clear "resumed from checkpoint" message when skipping > 0 chunks.

---

## Change Surface

| File | Change |
|---|---|
| `data-ingestion/src/processors/chunker.py` | Add `char_start`/`char_end` to all chunk dicts |
| `data-ingestion/src/processors/graph_creator.py` | `_normalize_entity()`, tier in schema/prompt, byte-range + tier in write, resume logic |
| `data-ingestion/src/retrieval/hybrid.py` | Read `graph_facts_limit` from config, parameterize LIMIT |
| `config/app.yaml` | `graph_facts_limit: 10`, tier in few-shot examples |

Tests to run after:

- `make ingestion-test-processors` — verifies chunker output shape
- `make ingestion-test-qdrant` — verifies retriever still works

---

## Key Constraints / Notes

- `MarkdownChunker._build_chunk_with_context()` prepends `"Context: {path}\n\n"` to content — `char_start`/`char_end` track the **raw section content** position in the cleaned markdown, not the augmented chunk string
- Cypher relationship TYPE cannot be parameterized — sanitization in `write_triplets` is intentional and must remain
- `tier` in Neo4j SET comes from each individual triplet dict; default=2 when the LLM omits it
- Old `*_chunks.json` files have no `char_start`/`char_end` — `process_chunks_dir` defaults both to `None`; Neo4j stores `null` for those edges (backward compat)

efore After
"Relation F1 13.3%" → looks broken Tier 1/2 get credit; Tier 3 labeled as inference
Can't verify any claim Byte-range pointer + one-click source verification path
"TYPE 2 DIABETES" and "TYPE2 DIABETES" = separate nodes Normalized → same node
Graph retrieval hardcoded to 5 facts Configurable (10, 20, whatever)
Crash at chunk 47 → restart from 0 Resume from last successful chunk
