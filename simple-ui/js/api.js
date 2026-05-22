/**
 * api.js — Fetch wrappers for the ClinicalMatch API (localhost:8000).
 * Exposed as window.API so Alpine.js components can call them directly.
 */

const API_BASE = "http://localhost:8000";
const INGEST_API_BASE = "http://localhost:8001";

window.API = {

  /**
   * POST /api/match — run hybrid retrieval for a clinical query.
   * @param {string} query  — natural language query
   * @param {File|null} file — optional CSV file
   * @returns {Promise<MatchResponse>}
   */
  async matchTrials(query, file = null) {
    const form = new FormData();
    form.append("query", query);
    if (file) form.append("file", file);

    const res = await fetch(`${API_BASE}/api/match`, {
      method: "POST",
      body: form,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    return res.json();
  },

  /**
   * GET /api/verify — retrieve a text snippet by byte range.
   * @param {string} source      — filename in data/artifacts/clean/
   * @param {number} byteStart
   * @param {number} byteEnd
   * @returns {Promise<VerifyResponse>}
   */
  async verifyChunk(source, byteStart, byteEnd) {
    const params = new URLSearchParams({ source, byte_start: byteStart, byte_end: byteEnd });
    const res = await fetch(`${API_BASE}/api/verify?${params}`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    return res.json();
  },

  /**
   * GET /api/stats — latest benchmark run summary.
   * @returns {Promise<StatsResponse>}
   */
  async getStats() {
    const res = await fetch(`${API_BASE}/api/stats`);
    if (!res.ok) return null;
    return res.json();
  },

  /**
   * Construct a PDF streaming URL for the given DOI path.
   * @param {string} doiPath — e.g. "10.64898/2026.03.17.26348414"
   * @returns {string}
   */
  getPdfUrl(doiPath) {
    return `${API_BASE}/api/pdf/${encodeURIComponent(doiPath)}`;
  },

  /**
   * GET /api/debug/heatmap — sentence-level cosine similarity.
   * @param {string} query
   * @param {number} chunkIndex
   * @returns {Promise<{query, sentences: [{text, score}]}>}
   */
  async getHeatmap(query, chunkIndex) {
    const params = new URLSearchParams({ query, chunk_index: chunkIndex });
    const res = await fetch(`${API_BASE}/api/debug/heatmap?${params}`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    return res.json();
  },

  /**
   * GET /api/debug/subgraph/{entity} — 1-hop Neo4j neighbourhood for D3 force graph.
   * @param {string} entity — entity name (uppercase preferred)
   * @returns {Promise<{entity, nodes, links}>}
   */
  async getSubgraph(entity) {
    const res = await fetch(`${API_BASE}/api/debug/subgraph/${encodeURIComponent(entity)}`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    return res.json();
  },
  /**
   * POST /api/synthesis — LLM synthesis over retrieved evidence.
   * @param {string} query
   * @param {Array<{head,relation,tail,tier}>} evidence — flattened from all matches
   * @returns {Promise<{synthesis, model, tokensUsed}>}
   */
  async synthesize(query, evidence) {
    const res = await fetch(`${API_BASE}/api/synthesis`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, evidence }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    return res.json();
  },

  // ── Ingestion Pipeline API (:8001) ──────────────────────────────────────────

  /**
   * POST /api/ingest — upload a PDF and stream SSE pipeline progress.
   * @param {File} file — PDF file to ingest
   * @param {function({stage,status,message,extra}): void} onEvent — called for each SSE event
   * @returns {Promise<string>} slug derived by server (from X-Slug response header)
   */
  async ingestPdf(file, onEvent) {
    const form = new FormData();
    form.append("file", file);

    const res = await fetch(`${INGEST_API_BASE}/api/ingest`, {
      method: "POST",
      body: form,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }

    const slug = res.headers.get("X-Slug") || file.name.replace(/\.pdf$/i, "");
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop(); // keep incomplete line
      for (const line of lines) {
        if (line.startsWith("data: ")) {
          try {
            const event = JSON.parse(line.slice(6));
            onEvent(event);
            // Only close the stream on the terminal pipeline-level sentinel events,
            // NOT on per-stage "done" — those must keep flowing.
            if (event.stage === "done" || event.stage === "error") return slug;
          } catch (_) { /* ignore malformed JSON */ }
        }
      }
    }
    return slug;
  },

  /**
   * GET /api/ingest/status — list processed docs and their stage completion.
   * @returns {Promise<{docs: Array<{slug,stages,ocr_pages}>}>}
   */
  async getIngestStatus() {
    const res = await fetch(`${INGEST_API_BASE}/api/ingest/status`);
    if (!res.ok) return { docs: [] };
    return res.json();
  },

  /**
   * Build a URL for an OCR debug PNG — served directly from the API.
   * @param {string} slug
   * @param {number} page — 1-based
   * @returns {string}
   */
  getOcrVizUrl(slug, page) {
    return `${INGEST_API_BASE}/api/ingest/artifacts/ocr-viz/${encodeURIComponent(slug)}/${page}`;
  },

  /**
   * GET /api/ingest/artifacts/{stage}/{slug} — fetch a pipeline artifact.
   * @param {'markdown'|'clean'|'chunks'} stage
   * @param {string} slug
   * @returns {Promise<object>}
   */
  async getArtifact(stage, slug) {
    const res = await fetch(
      `${INGEST_API_BASE}/api/ingest/artifacts/${stage}/${encodeURIComponent(slug)}`
    );
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    return res.json();
  },

  /**
   * GET /api/ingest/artifacts/kg-graph/{slug} — D3 force-graph data for the KG.
   * @param {string} slug
   * @returns {Promise<{slug, nodes, links}>}
   */
  async getKgGraph(slug) {
    const res = await fetch(
      `${INGEST_API_BASE}/api/ingest/artifacts/kg-graph/${encodeURIComponent(slug)}`
    );
    if (!res.ok) return { slug, nodes: [], links: [] };
    return res.json();
  },

};
