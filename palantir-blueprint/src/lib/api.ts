// Typed fetch wrappers for the clinical ops backend API.
// All functions throw on non-2xx responses.

// Keep requests same-origin. Vite proxies /api/ingest* to :8002 and all other
// /api* routes to :8000. This is required for authenticated image and PDF.js
// requests, which cannot attach the session's custom auth headers.
const API_BASE = "";
const INGEST_BASE = "";

// ─── Token management ──────────────────────────────────────────

const TOKEN_KEY = "clinical_auth_token";

export function getToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  sessionStorage.setItem(TOKEN_KEY, token);
  // Also persist as a cookie so it survives reverse-proxy header stripping.
  // SameSite=Strict + Path=/ scopes it to this origin only.
  document.cookie = `auth_token=${token}; SameSite=Strict; Path=/`;
}

export function clearToken(): void {
  sessionStorage.removeItem(TOKEN_KEY);
  // Expire the cookie immediately.
  document.cookie = "auth_token=; SameSite=Strict; Path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT";
}

function authHeaders(): Record<string, string> {
  const token = getToken();
  if (!token) return {};
  // RunPod nginx strips Authorization header — also send as X-Auth-Token
  return { Authorization: `Bearer ${token}`, "X-Auth-Token": token };
}

/** POST /api/auth/login — exchange username/password for a JWT. */
export async function login(username: string, password: string): Promise<void> {
  const form = new URLSearchParams();
  form.append("username", username);
  form.append("password", password);

  const res = await fetch(`${API_BASE}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: form.toString(),
  });

  if (!res.ok) {
    const payload: unknown = await res.json().catch(() => null);
    throw new ApiError(res.status, parseErrorDetail(payload, res.status));
  }

  const data = (await res.json()) as { access_token: string };
  setToken(data.access_token);
}

// ─── Backend types — reasoning API (/api/match) ────────────────

export type RetrievalTarget = "literature" | "patient_context";

export interface ActiveDocumentContext {
  filename: string;
  slug: string;
}

export interface RetrievalContext {
  target: RetrievalTarget;
  activeDocument: ActiveDocumentContext | null;
}

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
  collection?: string | null;
  scope?: string | null;
  source: string;
  content: string;
  context: string;
  pageNumber?: number | null;
  charStart?: number | null;
  charEnd?: number | null;
  evidence: BackendMatchEvidence[];
}

export interface BackendEmptyOutcome {
  code: "source_mismatch" | "source_not_indexed" | "no_relevant_evidence";
  message: string;
  action: string;
}

export interface BackendRetrievalContext {
  name: RetrievalTarget;
  collection: string;
  scope: string;
  source: string | null;
  source_slug: string | null;
}

/** Full response from POST /api/match (synchronous, no polling). */
export interface BackendMatchResponse {
  query: string;
  found: boolean;
  matches: BackendMatch[];
  graphFacts: string[];
  graphAnchor?: string | null;
  retrievalContext: BackendRetrievalContext | null;
  empty: BackendEmptyOutcome | null;
  evidenceId: string | null;
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

export type BackendSynthesisStreamEvent =
  | { type: "meta"; model: string | null; fallbackUsed: boolean }
  | { type: "token"; text: string }
  | { type: "done" }
  | { type: "error"; code: string | null; message: string; retryable: boolean };

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
  const headers: Record<string, string> = {
    ...authHeaders(),
    ...(init?.headers as Record<string, string> | undefined),
  };
  const res = await fetch(input, { ...init, headers });
  if (res.status === 401) {
    clearToken();
    window.dispatchEvent(new CustomEvent("auth:logout"));
    const payload: unknown = await res.json().catch(() => null);
    throw new ApiError(res.status, parseErrorDetail(payload, res.status));
  }
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
export function matchQuery(
  query: string,
  context: RetrievalContext,
  topK = 10,
  signal?: AbortSignal,
): Promise<BackendMatchResponse> {
  const form = new FormData();
  form.append("query", query);
  form.append("target", context.target);
  if (context.activeDocument) {
    form.append("source", context.activeDocument.filename);
    form.append("source_slug", context.activeDocument.slug);
  }
  form.append("top_k", String(topK));
  return fetchJson<BackendMatchResponse>(`${API_BASE}/api/match`, {
    method: "POST",
    body: form,
    signal,
  });
}

export async function fetchSynthesisStream(
  query: string,
  evidenceId: string,
  signal?: AbortSignal,
): Promise<Response> {
  const response = await fetch(`${API_BASE}/api/synthesis/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ query, evidenceId }),
    signal,
  });
  if (response.status === 401) {
    clearToken();
    window.dispatchEvent(new CustomEvent("auth:logout"));
  }
  if (!response.ok) {
    const payload: unknown = await response.json().catch(() => null);
    throw new ApiError(response.status, parseErrorDetail(payload, response.status));
  }
  return response;
}

export function fetchSubgraph(
  entity: string,
  context: RetrievalContext,
  signal?: AbortSignal,
): Promise<BackendSubgraphResponse> {
  const params = new URLSearchParams({ target: context.target });
  if (context.activeDocument) {
    params.set("source_slug", context.activeDocument.slug);
  }
  return fetchJson<BackendSubgraphResponse>(
    `${API_BASE}/api/debug/subgraph/${encodeURIComponent(entity)}?${params.toString()}`,
    { signal },
  );
}

// ─── Ingestion (ingestion API, :8002) ─────────────────────────

/**
 * POST /api/ingest — upload a PDF and stream 5-stage pipeline progress as SSE.
 * Returns raw Response so caller can consume the stream body.
 * The X-Slug response header contains the document slug for subsequent artifact fetches.
 */
export function startIngestStream(file: File, signal?: AbortSignal): Promise<Response> {
  const form = new FormData();
  form.append("file", file);
  return fetch(`${INGEST_BASE}/api/ingest`, {
    method: "POST",
    body: form,
    headers: authHeaders(),
    signal,
  });
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
