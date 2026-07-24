"""
graph_creator.py — Processor: Chunks → Neo4j knowledge graph via local LLM.

Extracts (head, relation, tail) medical triplets from chunk text using a
chat-completions endpoint (LM Studio / OpenAI-compatible), then writes them
to Neo4j as typed relationships.

Key design decisions vs. the standalone build_knowledge_graph.py script:
  - Single user-role message only: avoids Mistral template "system role not
    supported" crash.
  - One-shot example injected into every prompt: dramatically reduces
    zero-shot refusal rate on 7B instruction models.
  - response_format auto-detection: tries json_schema on first call; if the
    server returns HTTP 400, silently falls back to text mode + regex
    extraction so the processor works across all LM Studio versions.
  - JSON sanitizer: strips <think> CoT blocks (Qwen3), fixes trailing commas,
    extracts the first {...} object from free-text responses.
"""

import hashlib
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, TypeAlias

import requests
from neo4j import GraphDatabase

logger = logging.getLogger(__name__)

_MANIFEST_VERSION = 2
_MANIFEST_FILENAME = ".kg_progress.json"
Endpoint: TypeAlias = tuple[str, str, str]

# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

# Base template — relation_verbs and few_shot_section injected at runtime
# from config/app.yaml (knowledge_graph.relation_verbs / few_shot_examples).
_PROMPT_BASE = """\
Extract medical relation triplets from the text below.
Extract ALL relevant medical entities, including diseases, datasets, measures, and institutions.
Output ONLY valid JSON — no explanation, no markdown, no preamble.

Format:
{{"triplets": [{{"head": "EntityA", "relation": "VERB", "tail": "EntityB", "tier": 2}}]}}

Allowed relation verbs:
{relation_verbs}

Tier values (assign one per triplet):
1 = words appear verbatim in the text
2 = clearly stated or paraphrased
3 = logically inferred, not explicitly stated

{few_shot_section}
Text:
{chunk_text}

Output:"""

_DEFAULT_RELATION_VERBS = [
    "TREATS", "CAUSES", "PREVENTS", "INHIBITS", "INTERACTS_WITH",
    "PREDICTS", "MEASURED_BY", "ASSOCIATED_WITH", "REDUCES", "INCREASES",
    "DIVERGES_FROM", "DEFINED_BY",
]

# ---------------------------------------------------------------------------
# Entity normalisation
# ---------------------------------------------------------------------------

# Ordered list of (compiled_pattern, replacement) applied after uppercasing.
_ENTITY_NORM_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'\bTYPE\s+(\d+)\b'),         r'TYPE\1'),       # TYPE 2 → TYPE2
    (re.compile(r'\bCOVID[\s\-]*19\b'),        'COVID19'),       # COVID-19 / COVID 19 variants
    (re.compile(r'\s+'),                        ' '),             # collapse internal whitespace
]


def _normalize_entity(name: str) -> str:
    """
    Normalise an entity name for Neo4j deduplication.

    Steps:
      1. Uppercase + strip leading/trailing whitespace.
      2. Apply domain-specific regex rewrites (TYPE 2 → TYPE2, etc.).
      3. Strip trailing punctuation artifacts (commas, periods, semicolons).
    """
    name = name.upper().strip()
    for pattern, replacement in _ENTITY_NORM_PATTERNS:
        name = pattern.sub(replacement, name)
    return name.strip('.,;:')

_FALLBACK_FEW_SHOT = (
    'Example:\n'
    'Text: "Metformin treats type 2 diabetes and reduces HbA1c levels. '
    'Sepsis causes elevated lactate."\n'
    'Output: {"triplets":['
    '{"head":"Metformin","relation":"TREATS","tail":"type 2 diabetes","tier":1},'
    '{"head":"Metformin","relation":"REDUCES","tail":"HbA1c","tier":1},'
    '{"head":"Sepsis","relation":"CAUSES","tail":"elevated lactate","tier":1}]}'
)

# JSON schema sent when the LM Studio version supports it
_RESPONSE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "triplets_response",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "triplets": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "head":     {"type": "string"},
                            "relation": {"type": "string"},
                            "tail":     {"type": "string"},
                            "tier":     {"type": "integer"},
                        },
                        "required": ["head", "relation", "tail", "tier"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["triplets"],
            "additionalProperties": False,
        },
    },
}


# ---------------------------------------------------------------------------
# JSON sanitiser
# ---------------------------------------------------------------------------

def _find_json_end(s: str, start: int) -> int:
    """
    Find the index of the `}` that closes the `{` at *start*, respecting
    string escaping.  Returns -1 if the object is not fully closed.
    """
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(s)):
        c = s[i]
        if escape:
            escape = False
            continue
        if c == "\\" and in_string:
            escape = True
            continue
        if c == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
    return -1


def _sanitize_json(raw: str) -> dict:
    """
    Best-effort JSON extraction from an LLM response.

    Steps:
      1. Strip Qwen3 <think>…</think> chain-of-thought blocks.
      2. Extract a ```json … ``` fenced block if present.
      3. Otherwise find the opening `{` and locate its matching `}` via
         bracket-depth tracking.  If no matching `}` exists (truncated
         output), attempt repair via _repair_truncated_json.
      4. Remove trailing commas before ] or } (common LLM artefact).
      5. Parse with json.loads; raise ValueError on failure.
    """
    # 1. Strip CoT blocks
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

    # 2. Prefer fenced JSON block
    fenced = re.search(r"```json\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if fenced:
        candidate = fenced.group(1)
    else:
        start = raw.find("{")
        if start == -1:
            raise ValueError("No JSON object found in LLM response")
        end = _find_json_end(raw, start)
        if end == -1:
            # 3a. Truncated output — attempt bracket repair
            candidate = _repair_truncated_json(raw[start:])
        else:
            candidate = raw[start : end + 1]

    # 4. Remove trailing commas
    candidate = re.sub(r",\s*([}\]])", r"\1", candidate)

    return json.loads(candidate)


def _repair_truncated_json(fragment: str) -> str:
    """
    Attempt to close a JSON fragment that was cut off before its final `}`.

    Strategy: discard the incomplete trailing object (everything after the
    last `},` which marks the end of a fully-formed array element), then
    close the remaining open brackets.  Returns an empty-triplets object if
    no complete element exists at all.
    """
    last_complete = fragment.rfind("},")
    if last_complete == -1:
        # No complete objects found — return empty result rather than garbage
        return '{"triplets":[]}'

    # Keep up to and including the last complete `}`
    fragment = fragment[: last_complete + 1]

    # Close unclosed brackets
    opens = fragment.count("{") - fragment.count("}")
    arr_opens = fragment.count("[") - fragment.count("]")
    fragment += "]" * max(arr_opens, 0) + "}" * max(opens, 0)
    return fragment


# ---------------------------------------------------------------------------
# GraphCreator processor
# ---------------------------------------------------------------------------

class GraphCreator:
    """
    Extracts medical triplets from chunk text via a local LLM and writes them
    to Neo4j.

    Args:
        config: Full data_ingestion config dict (the value under
                ``data_ingestion`` in config/app.yaml).  Reads sub-keys
                ``neo4j`` and ``knowledge_graph``.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        neo4j_cfg: dict = config.get("neo4j", {})
        kg_cfg: dict = config.get("knowledge_graph", {})

        self.chat_url: str = kg_cfg.get(
            "chat_url", "http://localhost:1234/v1/chat/completions"
        )
        self.model: str = kg_cfg.get("model", "qwen3-8b")
        self.fallback_chat_url: str | None = kg_cfg.get("fallback_chat_url")
        self.fallback_model: str | None = kg_cfg.get("fallback_model")
        self.health_timeout: float = float(kg_cfg.get("health_timeout_seconds", 2))
        self.max_retries: int = kg_cfg.get("max_retries", 2)
        self.timeout: int = kg_cfg.get("timeout_seconds", 180)
        self.max_tokens: int = kg_cfg.get("max_tokens", 768)
        self.max_chars: int = kg_cfg.get("max_text_chars", 1500)
        self.min_chars: int = kg_cfg.get("min_chunk_chars", 50)
        chunk_cfg: dict = config.get("chunking", {})
        self.filter_boilerplate: bool = chunk_cfg.get("filter_boilerplate", True)

        # Build relation verbs string from config (or defaults)
        relation_verbs: list[str] = kg_cfg.get("relation_verbs", _DEFAULT_RELATION_VERBS)
        self._relation_verbs_str: str = ", ".join(relation_verbs)

        # Build few-shot block from config examples (or fallback to single example)
        few_shot_examples: list[dict] = kg_cfg.get("few_shot_examples", [])
        if few_shot_examples:
            parts = ["Few-shot examples — follow these exactly:\n"]
            for ex in few_shot_examples:
                parts.append(f'Text: "{ex["text"]}"\nOutput: {ex["output"]}\n')
            self._few_shot_text: str = "\n".join(parts)
        else:
            self._few_shot_text = _FALLBACK_FEW_SHOT

        neo4j_uri: str = neo4j_cfg.get("uri", "bolt://localhost:7687")
        neo4j_auth: tuple[str, str] = (
            neo4j_cfg.get("user", "neo4j"),
            neo4j_cfg.get("password", "testpassword"),
        )

        # None → not yet probed; True/False → result of first call
        self._json_schema_supported: bool | None = None
        self._primary_endpoint: Endpoint = ("primary", self.chat_url, self.model)
        self._fallback_endpoint: Endpoint | None = (
            ("fallback", self.fallback_chat_url, self.fallback_model)
            if self.fallback_chat_url and self.fallback_model
            else None
        )
        self._active_chat_url = self.chat_url
        self._active_model = self.model

        try:
            self._driver = GraphDatabase.driver(neo4j_uri, auth=neo4j_auth)
            self._driver.verify_connectivity()
            logger.info("GraphCreator: connected to Neo4j at %s", neo4j_uri)
        except Exception as exc:
            logger.critical("GraphCreator: Neo4j connection failed: %s", exc)
            raise

    def close(self) -> None:
        self._driver.close()

    # ── prompt ────────────────────────────────────────────────────────────────

    def _build_prompt(self, text: str) -> str:
        return _PROMPT_BASE.format(
            relation_verbs=self._relation_verbs_str,
            few_shot_section=self._few_shot_text,
            chunk_text=text[: self.max_chars],
        )

    # ── LLM call ──────────────────────────────────────────────────────────────

    @staticmethod
    def _health_url(chat_url: str) -> str:
        """Return the local server health endpoint associated with a chat URL."""
        marker = "/v1/chat/completions"
        if marker in chat_url:
            return f"{chat_url.split(marker, 1)[0]}/health"
        marker = "/chat/completions"
        if marker in chat_url:
            return f"{chat_url.split(marker, 1)[0]}/health"
        return f"{chat_url.rstrip('/')}/health"

    def _is_endpoint_healthy(self, endpoint: Endpoint) -> bool:
        """Check a local inference endpoint without submitting clinical text."""
        name, chat_url, _ = endpoint
        health_url = self._health_url(chat_url)
        try:
            response = requests.get(health_url, timeout=self.health_timeout)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            logger.info(
                "event=kg_endpoint_unhealthy endpoint=%s reason=%s",
                name,
                type(exc).__name__,
            )
            return False
        except requests.exceptions.RequestException as exc:
            logger.info(
                "event=kg_endpoint_unhealthy endpoint=%s reason=%s",
                name,
                type(exc).__name__,
            )
            return False

        if response.ok:
            return True
        logger.info(
            "event=kg_endpoint_unhealthy endpoint=%s status=%s",
            name,
            response.status_code,
        )
        return False

    def _select_healthy_endpoint(self) -> Endpoint | None:
        """Prefer SGLang and use the configured local fallback only when needed."""
        if self._is_endpoint_healthy(self._primary_endpoint):
            return self._primary_endpoint
        if self._fallback_endpoint and self._is_endpoint_healthy(self._fallback_endpoint):
            logger.info("event=kg_endpoint_selected endpoint=fallback")
            return self._fallback_endpoint
        logger.warning(
            "event=kg_extractor_unavailable primary=%s fallback_configured=%s",
            self.chat_url,
            self._fallback_endpoint is not None,
        )
        return None

    def _healthy_fallback(self) -> Endpoint | None:
        """Return a verified fallback endpoint for a post-health connection loss."""
        if self._fallback_endpoint and self._is_endpoint_healthy(self._fallback_endpoint):
            return self._fallback_endpoint
        return None

    def _activate_endpoint(self, endpoint: Endpoint) -> None:
        """Set the request target selected by the endpoint health check."""
        _, self._active_chat_url, self._active_model = endpoint

    def _post(self, prompt: str, use_schema: bool) -> requests.Response:
        payload: dict[str, Any] = {
            "model": self._active_model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "temperature": 0.0,
            "max_tokens": self.max_tokens,
            # Penalise repetition hard — prevents the hallucination loop seen
            # when grammar-constrained models run out of meaningful content.
            "repeat_penalty": 1.3,
            "repeat_last_n": 128,
        }
        if use_schema:
            payload["response_format"] = _RESPONSE_SCHEMA

        return requests.post(
            self._active_chat_url,
            headers={"Authorization": "Bearer lm-studio"},
            json=payload,
            timeout=self.timeout,
        )

    def _post_with_failover(
        self, prompt: str, use_schema: bool, endpoint: Endpoint
    ) -> tuple[requests.Response, Endpoint]:
        """Post once, retrying a primary connection loss on a healthy fallback."""
        self._activate_endpoint(endpoint)
        try:
            return self._post(prompt, use_schema), endpoint
        except requests.exceptions.ConnectionError:
            if endpoint[0] != "primary":
                raise
            fallback = self._healthy_fallback()
            if fallback is None:
                raise
            logger.warning("event=kg_endpoint_failover from=primary to=fallback")
            self._activate_endpoint(fallback)
            return self._post(prompt, use_schema), fallback

    def extract_triplets(self, text: str) -> list[dict] | None:
        """
        Send *text* to the configured LLM and return validated triplets.

        Returns:
            List of triplet dicts on success (may be empty if nothing to extract).
            ``None`` when all retry attempts fail — callers must NOT mark the
            chunk as processed so it is retried on the next run.

        Auto-detects json_schema support on the first call: if the server
        returns HTTP 400 whose body references ``response_format`` or
        ``json_schema``, the schema is disabled for the remainder of the
        session.  Other 400s (e.g. model loading failures) are treated as
        transient errors and do NOT change the schema flag.
        """
        if len(text) < self.min_chars:
            return []

        prompt = self._build_prompt(text)
        endpoint = self._select_healthy_endpoint()
        if endpoint is None:
            return None

        for attempt in range(self.max_retries):
            use_schema = self._json_schema_supported is not False
            try:
                resp, endpoint = self._post_with_failover(
                    prompt, use_schema=use_schema, endpoint=endpoint
                )

                # Distinguish a genuine json_schema rejection from other 400s
                # (e.g. "Failed to load model") before downgrading schema mode.
                if resp.status_code == 400 and use_schema:
                    body = resp.text.lower()
                    if "response_format" in body or "json_schema" in body:
                        logger.info(
                            "Server rejected response_format; switching to text mode"
                        )
                        self._json_schema_supported = False
                        resp, endpoint = self._post_with_failover(
                            prompt, use_schema=False, endpoint=endpoint
                        )
                    else:
                        logger.warning(
                            "LLM HTTP 400 (attempt %d) — not a schema error: %s",
                            attempt + 1,
                            resp.text[:200],
                        )
                        time.sleep(2**attempt)
                        continue

                if resp.status_code != 200:
                    logger.warning(
                        "LLM HTTP %s (attempt %d): %s",
                        resp.status_code,
                        attempt + 1,
                        resp.text[:200],
                    )
                    time.sleep(2**attempt)
                    continue

                if use_schema and self._json_schema_supported is None:
                    self._json_schema_supported = True

                raw_content: str = resp.json()["choices"][0]["message"]["content"]
                parsed = _sanitize_json(raw_content)
                triplets: list[dict] = parsed.get("triplets", []) or parsed.get(
                    "relations", []
                )
                valid = [
                    t for t in triplets if {"head", "relation", "tail"} <= t.keys()
                ]
                logger.debug("Extracted %d triplets", len(valid))
                return valid

            except (KeyError, IndexError):
                logger.warning("Unexpected response schema (attempt %d)", attempt + 1)
            except (json.JSONDecodeError, ValueError) as exc:
                logger.warning("JSON parse error (attempt %d): %s", attempt + 1, exc)
            except requests.exceptions.Timeout:
                logger.warning(
                    "LLM timeout (attempt %d/%d)", attempt + 1, self.max_retries
                )
            except requests.exceptions.ConnectionError:
                logger.warning(
                    "LLM connection error (attempt %d/%d)",
                    attempt + 1,
                    self.max_retries,
                )
            except Exception as exc:
                logger.error("Extraction error: %s", exc, exc_info=True)

            if attempt < self.max_retries - 1:
                time.sleep(2**attempt)

        logger.warning("extract_triplets: all %d attempts failed — chunk will not be marked done", self.max_retries)
        return None

    # ── Neo4j write ───────────────────────────────────────────────────────────

    def write_triplets(
        self,
        triplets: list[dict],
        source_file: str,
        chunk_id: int,
        byte_start: int | None = None,
        byte_end: int | None = None,
        scope: str = "literature",
    ) -> int:
        """Upsert *triplets* into Neo4j as typed Entity relationships.

        Args:
            triplets:    Validated triplet dicts with head/relation/tail (and optional tier).
            source_file: Stem of the source chunk file (written to r.source).
            chunk_id:    Index of the chunk within the source file.
            byte_start:  Character offset of the chunk's raw content in the cleaned markdown.
            byte_end:    End character offset (exclusive) of the chunk's raw content.
            scope:       Data domain used to keep literature and patient facts separate.

        Returns:
            Number of source-scoped relationships written.
        """
        if not triplets:
            return 0

        with self._driver.session() as session:
            for t in triplets:
                head = _normalize_entity(t["head"])
                tail = _normalize_entity(t["tail"])
                tier: int = int(t.get("tier", 2))
                raw_rel = (
                    t["relation"].strip().upper().replace(" ", "_").replace("-", "_")
                )
                # Cypher relationship TYPE cannot be parameterized — sanitized here.
                rel_type = (
                    "".join(c for c in raw_rel if c.isalnum() or c == "_")
                    or "RELATED_TO"
                )

                query = f"""
                MERGE (h:Entity {{name: $head}})
                MERGE (t:Entity {{name: $tail}})
                MERGE (h)-[r:{rel_type} {{
                    source: $source, chunk_id: $chunk_id, scope: $scope
                }}]->(t)
                SET r.byte_start = $byte_start, r.byte_end = $byte_end, r.tier = $tier
                """
                session.run(
                    query,
                    head=head,
                    tail=tail,
                    source=source_file,
                    chunk_id=chunk_id,
                    scope=scope,
                    byte_start=byte_start,
                    byte_end=byte_end,
                    tier=tier,
                )

        logger.info(
            "  → graph: +%d relations from %s chunk %d scope=%s",
            len(triplets), source_file, chunk_id, scope,
        )
        return len(triplets)

    # ── resume helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _new_manifest() -> dict[str, Any]:
        return {"version": _MANIFEST_VERSION, "documents": {}}

    def _load_manifest(self, chunks_dir: Path) -> tuple[dict[str, Any], bool]:
        """Load the versioned extraction manifest, invalidating legacy progress."""
        path = chunks_dir / _MANIFEST_FILENAME
        if not path.exists():
            return self._new_manifest(), False
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not read KG manifest (%s); rebuilding sources", exc)
            return self._new_manifest(), True

        if (
            isinstance(raw, dict)
            and raw.get("version") == _MANIFEST_VERSION
            and isinstance(raw.get("documents"), dict)
        ):
            return raw, False

        logger.warning(
            "event=kg_legacy_manifest_invalidated path=%s", path.name
        )
        return self._new_manifest(), True

    def _save_manifest(self, chunks_dir: Path, manifest: dict[str, Any]) -> None:
        """Persist the manifest atomically so interrupted runs remain resumable."""
        path = chunks_dir / _MANIFEST_FILENAME
        pending_path = chunks_dir / f"{_MANIFEST_FILENAME}.pending"
        try:
            pending_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
            )
            pending_path.replace(path)
        except OSError as exc:
            logger.error("Could not persist KG manifest: %s", exc, exc_info=True)
            try:
                pending_path.unlink(missing_ok=True)
            except OSError:
                logger.debug("Could not clean up pending KG manifest", exc_info=True)
            raise

    def _document_fingerprint(self, data: Any) -> str:
        """Fingerprint chunk content and all settings that affect extraction output."""
        chunks = data.get("chunks", []) if isinstance(data, dict) else data
        fingerprint_input = {
            "chunks": chunks,
            "model": self.model,
            "chat_url": self.chat_url,
            "fallback_model": self.fallback_model,
            "fallback_chat_url": self.fallback_chat_url,
            "max_tokens": self.max_tokens,
            "max_text_chars": self.max_chars,
            "min_chunk_chars": self.min_chars,
            "relation_verbs": self._relation_verbs_str,
            "few_shot_examples": self._few_shot_text,
        }
        serialized = json.dumps(
            fingerprint_input, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def purge_source(self, source_file: str, scope: str = "literature") -> int:
        """Delete only relationships belonging to a source scope, never entities."""
        query = """
        MATCH ()-[r]->()
        WHERE r.source = $source AND (r.scope = $scope OR r.scope IS NULL)
        DELETE r
        RETURN count(r) AS deleted
        """
        with self._driver.session() as session:
            result = session.run(query, source=source_file, scope=scope)
            record = result.single()
        deleted = int(record["deleted"]) if record and "deleted" in record else 0
        logger.info(
            "event=kg_source_purged source=%s scope=%s relationships=%d",
            source_file,
            scope,
            deleted,
        )
        return deleted

    # ── pipeline entry-point ──────────────────────────────────────────────────

    def process_chunks_file(
        self, file_path: Path, scope: str = "literature", force: bool = False
    ) -> int:
        """
        Process one ``*_chunks.json`` file and return relationships written.

        A source is rebuilt after a manifest version/fingerprint mismatch or
        ``force=True``. Only its own relationships are purged before rebuilding.
        Failed extraction attempts remain unrecorded and are retried next run.
        A successful empty response is explicitly recorded as a zero-triplet
        chunk rather than being confused with an extraction failure.
        """
        chunks_dir = file_path.parent
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Could not read chunk file %s: %s", file_path, exc, exc_info=True)
            return 0

        chunks: list[dict[str, Any]] = (
            data.get("chunks", []) if isinstance(data, dict) else data
        )
        if not isinstance(chunks, list):
            logger.error("Chunk file %s has a non-list chunks payload", file_path)
            return 0

        manifest, legacy_manifest = self._load_manifest(chunks_dir)
        documents: dict[str, Any] = manifest["documents"]
        file_key = file_path.stem
        fingerprint = self._document_fingerprint(data)
        existing = documents.get(file_key)
        stale = (
            legacy_manifest
            or force
            or not isinstance(existing, dict)
            or existing.get("fingerprint") != fingerprint
            or existing.get("scope") != scope
        )
        if stale:
            reason = (
                "legacy" if legacy_manifest else "force" if force else "fingerprint"
            )
            logger.info(
                "event=kg_source_rebuild source=%s scope=%s reason=%s",
                file_key,
                scope,
                reason,
            )
            self.purge_source(file_key, scope)
            document: dict[str, Any] = {
                "fingerprint": fingerprint,
                "scope": scope,
                "processed_chunks": [],
                "zero_triplet_chunks": [],
                "triplet_count": 0,
                "complete": False,
            }
            documents[file_key] = document
            self._save_manifest(chunks_dir, manifest)
        else:
            document = existing

        processed_chunks = {
            int(index)
            for index in document.get("processed_chunks", [])
            if isinstance(index, int)
        }
        zero_triplet_chunks = {
            int(index)
            for index in document.get("zero_triplet_chunks", [])
            if isinstance(index, int)
        }
        eligible_chunks = {
            index
            for index, chunk in enumerate(chunks)
            if isinstance(chunk, dict)
            and len(str(chunk.get("content", ""))) >= self.min_chars
            and not (self.filter_boilerplate and chunk.get("is_boilerplate", False))
        }
        total_triplets = 0

        for index in sorted(eligible_chunks):
            if index in processed_chunks:
                continue
            chunk = chunks[index]
            content = str(chunk.get("content", ""))
            logger.info("  Chunk %d/%d — extracting triplets…", index + 1, len(chunks))
            try:
                triplets = self.extract_triplets(content)
                if triplets is None:
                    logger.warning(
                        "event=kg_chunk_unprocessed source=%s chunk=%d reason=extractor_unavailable",
                        file_key,
                        index,
                    )
                    continue
                written = self.write_triplets(
                    triplets,
                    file_key,
                    index,
                    byte_start=chunk.get("char_start"),
                    byte_end=chunk.get("char_end"),
                    scope=scope,
                )
            except KeyboardInterrupt:
                logger.info("Interrupted at chunk %d/%d. Re-run to resume.", index + 1, len(chunks))
                raise
            except Exception as exc:
                logger.error(
                    "event=kg_chunk_unprocessed source=%s chunk=%d reason=%s",
                    file_key,
                    index,
                    type(exc).__name__,
                    exc_info=True,
                )
                continue

            processed_chunks.add(index)
            if written == 0:
                zero_triplet_chunks.add(index)
            else:
                zero_triplet_chunks.discard(index)
            total_triplets += written
            document["processed_chunks"] = sorted(processed_chunks)
            document["zero_triplet_chunks"] = sorted(zero_triplet_chunks)
            document["triplet_count"] = int(document.get("triplet_count", 0)) + written
            document["complete"] = processed_chunks >= eligible_chunks
            self._save_manifest(chunks_dir, manifest)

        document["processed_chunks"] = sorted(processed_chunks)
        document["zero_triplet_chunks"] = sorted(zero_triplet_chunks)
        document["complete"] = processed_chunks >= eligible_chunks
        self._save_manifest(chunks_dir, manifest)
        logger.info(
            "event=kg_source_complete source=%s scope=%s complete=%s triplets_written=%d "
            "zero_triplet_chunks=%d",
            file_key,
            scope,
            document["complete"],
            total_triplets,
            len(zero_triplet_chunks),
        )
        return total_triplets

    def process_chunks_dir(
        self, chunks_dir: Path, scope: str = "literature", force: bool = False
    ) -> int:
        """Process all ``*_chunks.json`` files and return relationships written."""
        chunk_files = sorted(chunks_dir.glob("*_chunks.json"))
        if not chunk_files:
            logger.warning("No *_chunks.json files found in %s", chunks_dir)
            return 0

        logger.info(
            "GraphCreator: found %d chunk file(s) scope=%s force=%s",
            len(chunk_files),
            scope,
            force,
        )
        total_triplets = 0
        for file_path in chunk_files:
            logger.info("Processing: %s", file_path.name)
            total_triplets += self.process_chunks_file(
                file_path, scope=scope, force=force
            )

        logger.info(
            "GraphCreator: complete — %d total triplets written", total_triplets
        )
        return total_triplets
