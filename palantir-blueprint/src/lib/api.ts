// Typed fetch wrappers for the clinical ops backend API.
// All functions throw on non-2xx responses.

// On RunPod (and any deployment behind a reverse proxy), use relative URLs so
// Vite's dev/preview proxy can forward /api → :8000 and /ingest-api → :8001
// without the browser needing direct access to those ports.
// Override at build time via VITE_API_BASE_URL / VITE_INGEST_API_BASE_URL.

// Reasoning API (query, match, KG)
const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "";
// Ingestion API (ingest, artifacts)
const INGEST_BASE = (import.meta.env.VITE_INGEST_API_BASE_URL as string | undefined) ?? "";

// ─── Backend types — reasoning API (/api/match) ────────────────

/** One evidence triplet attached to a match chunk. */
export interface BackendMatchEvidence {
  head: string;
  relation: string;
  tail: string;
  tier: number;
  source: string;
  byteStart: number;
  byteEnd: number;
}

/** A single retrieved chunk from POST /api/match. */
export interface BackendMatch {
  chunkIndex: number;
  score: number;
  rankScore?: number | null;
  source: string;
  content: string;
  context: string;
  evidence: BackendMatchEvidence[];
}

/** Full response from POST /api/match (synchronous, no polling). */
export interface BackendMatchResponse {
  query: string;
  found: boolean;
  matches: BackendMatch[];
  graphFacts: string[];
  graphAnchor?: string | null;
  latency_ms: number;
}

// ─── Backend types — subgraph API (/api/debug/subgraph) ────────

export interface BackendSubgraphNode {
  id: string;
  label: string;
  tier: number;
}

export interface BackendSubgraphLink {
  source: string;
  target: string;
  relation: string;
}

export interface BackendSubgraphResponse {
  entity: string;
  nodes: BackendSubgraphNode[];
  links: BackendSubgraphLink[];
}

// ─── Backend types — ingestion artifacts ──────────────────────

/** One chunk from GET /api/ingest/artifacts/chunks/{slug} (matches MarkdownChunker output) */
export interface BackendChunk {
  content: string;       // full text with breadcrumb prefix "Context: A > B\n\n..."
  context: string;       // breadcrumb path, e.g. "Methods > Data Sources"
  level: number;
  page_number: number | null;
  is_boilerplate: boolean;
  char_start: number;
  char_end: number;
}

/** Response from GET /api/ingest/artifacts/chunks/{slug} */
export interface BackendChunksResponse {
  slug: string;
  total_chunks: number;
  chunk_config: Record<string, unknown>;
  sample_chunks: BackendChunk[];
}

/** Response from GET /api/ingest/artifacts/markdown/{slug} or /clean/{slug} */
export interface BackendArtifactPreviewResponse {
  slug: string;
  chars: number;
  preview: string;
}

export interface BackendSynthesisResponse {
  synthesis: string;
  model: string | null;
  fallbackUsed: boolean;
  tokensUsed: number | null;
}

export interface ApiErrorDetail {
  code: string | null;
  message: string;
  retryable: boolean;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly retryable: boolean;

  constructor(status: number, detail: ApiErrorDetail) {
    super(detail.message);
    this.name = "ApiError";
    this.status = status;
    this.code = detail.code;
    this.retryable = detail.retryable;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function parseErrorDetail(payload: unknown, status: number): ApiErrorDetail {
  const detail = isRecord(payload) && isRecord(payload.detail) ? payload.detail : null;
  const code = typeof detail?.code === "string" ? detail.code : null;
  return {
    code,
    message: code === "synthesis_unavailable"
      ? "Synthesis is temporarily unavailable. Retrieved evidence remains available."
      : typeof detail?.message === "string"
      ? detail.message
      : `Request failed (${status}). Please try again.`,
    retryable: detail?.retryable === true,
  };
}

async function fetchJson<T>(input: RequestInfo, init?: RequestInit): Promise<T> {
  const res = await fetch(input, init);
  if (!res.ok) {
    const payload: unknown = await res.json().catch(() => null);
    throw new ApiError(res.status, parseErrorDetail(payload, res.status));
  }
  return res.json() as Promise<T>;
}

// ─── Query & Retrieval (reasoning API, :8000) ──────────────────

/**
 * POST /api/match — synchronous GraphRAG retrieval. Returns matches directly.
 * Uses multipart/form-data as required by the FastAPI Form(...) parameter.
 */
export function matchQuery(query: string, topK = 10): Promise<BackendMatchResponse> {
  const form = new FormData();
  form.append("query", query);
  form.append("top_k", String(topK));
  return fetchJson<BackendMatchResponse>(`${API_BASE}/api/match`, { method: "POST", body: form });
}

/**
 * POST /api/synthesis — Phase 2 LLM synthesis grounded in cached GraphRAG evidence.
 * Pass the raw matches from /api/match; the server reuses its cached retrieval result.
 */
export function fetchSynthesis(query: string, evidence: unknown[]): Promise<BackendSynthesisResponse> {
  return fetchJson<BackendSynthesisResponse>(`${API_BASE}/api/synthesis`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, evidence }),
  });
}


export function fetchSubgraph(entity: string): Promise<BackendSubgraphResponse> {
  return fetchJson<BackendSubgraphResponse>(
    `${API_BASE}/api/debug/subgraph/${encodeURIComponent(entity)}`
  );
}

// ─── Ingestion (ingestion API, :8001) ─────────────────────────

/**
 * POST /api/ingest — upload a PDF and stream 5-stage pipeline progress as SSE.
 * Returns raw Response so caller can consume the stream body.
 * The X-Slug response header contains the document slug for subsequent artifact fetches.
 */
export function startIngestStream(file: File): Promise<Response> {
  const form = new FormData();
  form.append("file", file);
  return fetch(`${INGEST_BASE}/api/ingest`, { method: "POST", body: form });
}

/** GET /api/ingest/artifacts/chunks/{slug} — first 10 sample chunks. */
export function fetchChunks(slug: string): Promise<BackendChunksResponse> {
  return fetchJson<BackendChunksResponse>(`${INGEST_BASE}/api/ingest/artifacts/chunks/${slug}`);
}

/** GET /api/ingest/artifacts/markdown/{slug} — raw converted markdown preview. */
export function fetchMarkdownArtifact(slug: string): Promise<BackendArtifactPreviewResponse> {
  return fetchJson<BackendArtifactPreviewResponse>(
    `${INGEST_BASE}/api/ingest/artifacts/markdown/${slug}`
  );
}

/** GET /api/ingest/artifacts/clean/{slug} — PII-cleaned markdown preview. */
export function fetchCleanArtifact(slug: string): Promise<BackendArtifactPreviewResponse> {
  return fetchJson<BackendArtifactPreviewResponse>(
    `${INGEST_BASE}/api/ingest/artifacts/clean/${slug}`
  );
}

/** Returns the URL for an OCR debug visualization PNG (served by the ingestion API). */
export function getOcrVizUrl(slug: string, page: number): string {
  return `${INGEST_BASE}/api/ingest/artifacts/ocr-viz/${slug}/${page}`;
}

/**
 * Returns the URL to serve a source PDF by filename.
 * Backend: GET /api/ingest/artifacts/pdf?source={filename}
 * Searches data/pdfs/raw/ and data/pdfs/raw/upload/ for the matching file.
 */
export function getPdfSourceUrl(source: string): string {
  return `${INGEST_BASE}/api/ingest/artifacts/pdf?source=${encodeURIComponent(source)}`;
}
