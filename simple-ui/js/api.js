/**
 * api.js — Fetch wrappers for the ClinicalMatch API (localhost:8000).
 * Exposed as window.API so Alpine.js components can call them directly.
 */

const API_BASE = "http://localhost:8000";

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

};
