// Typed fetch wrappers for the clinical ops backend API.
// All functions throw on non-2xx responses.

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://localhost:8000";

// ─── Shared backend types ──────────────────────────────────────

export interface BackendProvenance {
  source_document: string;
  byte_range: [number, number];
  highlighted_text: string;
  confidence_score: number;
}

export interface BackendResult {
  id: string;
  trial_id: string;
  title: string;
  snippet: string;
  relevance_score: number;
  provenance: BackendProvenance[];
  matched_criteria: string[];
  // Optional enrichment fields the backend may include in metadata
  metadata?: {
    phase?: string;
    sponsor?: string;
    enrollment_status?: string;
    strategy?: string;
    page_number?: number;
    token_count?: number;
    [key: string]: unknown;
  };
}

export interface BackendKGNode {
  id: string;
  label: string;
  type: "trial" | "condition" | "intervention" | "outcome" | "document";
  metadata?: Record<string, unknown>;
}

export interface BackendKGEdge {
  source: string;
  target: string;
  label: string;
  weight?: number;
}

export interface BackendKGResponse {
  nodes: BackendKGNode[];
  edges: BackendKGEdge[];
  query_focus_node: string | null;
}

export interface BackendQuerySubmitResponse {
  query_id: string;
  status: "processing";
  estimated_time: number | null;
}

export interface BackendQueryResultsResponse {
  query_id: string;
  status: "completed" | "processing" | "failed";
  results: BackendResult[] | null;
  error: string | null;
}

export interface BackendOCRBlock {
  text: string;
  confidence: number;
  bbox: [number, number, number, number]; // [x0, y0, x1, y1] pixels
}

export interface BackendOCRPage {
  page_number: number;
  width: number;
  height: number;
  blocks: BackendOCRBlock[];
}

export interface BackendOCRDebugResponse {
  pages: BackendOCRPage[];
}

export interface BackendChunk {
  chunk_id: string;
  text: string;
  section_title: string;
  depth: number;
  parent_id: string | null;
  char_start: number;
  char_end: number;
  metadata: {
    source_document?: string;
    token_count?: number;
    page_number?: number;
    [key: string]: unknown;
  };
}

export interface BackendChunksResponse {
  chunks: BackendChunk[];
}

export interface BackendMarkdownResponse {
  markdown: string;
  cleaning_log: string[];
}

export interface BackendIngestJobStatus {
  job_id: string;
  status: "pending" | "processing" | "completed" | "failed";
  progress: Array<{
    step: string;
    status: string;
    progress: number;
    message: string;
    started_at: string | null;
    completed_at: string | null;
  }>;
}

// ─── Helpers ──────────────────────────────────────────────────

async function fetchJson<T>(input: RequestInfo, init?: RequestInit): Promise<T> {
  const res = await fetch(input, init);
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status} ${res.statusText}${body ? `: ${body}` : ""}`);
  }
  return res.json() as Promise<T>;
}

// ─── Query & Retrieval ─────────────────────────────────────────

export interface QueryFilters {
  condition?: string;
  phase?: string;
  status?: string;
}

export function submitQuery(
  query: string,
  options: { topK?: number; rerank?: boolean; filters?: QueryFilters } = {}
): Promise<BackendQuerySubmitResponse> {
  return fetchJson<BackendQuerySubmitResponse>(`${API_BASE}/api/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query,
      top_k: options.topK ?? 10,
      rerank: options.rerank ?? true,
      filters: options.filters ?? {},
    }),
  });
}

export function fetchQueryResults(queryId: string): Promise<BackendQueryResultsResponse> {
  return fetchJson<BackendQueryResultsResponse>(`${API_BASE}/api/query/${queryId}/results`);
}

export function fetchKnowledgeGraph(queryId: string): Promise<BackendKGResponse> {
  return fetchJson<BackendKGResponse>(`${API_BASE}/api/query/${queryId}/knowledge-graph`);
}

// ─── Ingestion ────────────────────────────────────────────────

/**
 * POST /api/ingest — returns a raw Response so the caller can consume the SSE stream.
 * The caller is responsible for reading the response body as a stream (EventSource can't do POST).
 */
export function startIngestStream(file: File, sourceId?: string): Promise<Response> {
  const form = new FormData();
  form.append("file", file);
  if (sourceId) form.append("source_id", sourceId);
  return fetch(`${API_BASE}/api/ingest`, { method: "POST", body: form });
}

export function fetchIngestJobStatus(jobId: string): Promise<BackendIngestJobStatus> {
  return fetchJson<BackendIngestJobStatus>(`${API_BASE}/api/ingest/${jobId}/status`);
}

export function fetchOCRDebug(jobId: string): Promise<BackendOCRDebugResponse> {
  return fetchJson<BackendOCRDebugResponse>(`${API_BASE}/api/ingest/${jobId}/debug/ocr`);
}

export function fetchChunks(jobId: string): Promise<BackendChunksResponse> {
  return fetchJson<BackendChunksResponse>(`${API_BASE}/api/ingest/${jobId}/chunks`);
}

export function fetchMarkdown(jobId: string): Promise<BackendMarkdownResponse> {
  return fetchJson<BackendMarkdownResponse>(`${API_BASE}/api/ingest/${jobId}/markdown`);
}
