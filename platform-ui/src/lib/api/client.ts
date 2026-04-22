/**
 * Typed HTTP client for the agentic-reasoning FastAPI server.
 * Base URL is controlled by NEXT_PUBLIC_API_URL (defaults to http://localhost:8000).
 */

import type { ExecutionLog } from "@/lib/types/audit";

const BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ── Request / Response shapes ─────────────────────────────────────────────────

export interface QueryPayload {
  query: string;
  tools?: string[];
  mode?: "langgraph" | "temporal";
  agent_config?: string;
}

export interface QueryResponse {
  synthesis: string;
  executionLog: ExecutionLog;
  toolResults: Record<string, string>;
}

export interface HealthResponse {
  status: string;
  version: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

async function apiFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });

  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`API ${res.status}: ${body || res.statusText}`);
  }

  return res.json() as Promise<T>;
}

// ── Public API ────────────────────────────────────────────────────────────────

/**
 * Run an agent query against the reasoning server.
 * Returns the full synthesis text, execution log, and per-tool results.
 */
export async function queryAgent(payload: QueryPayload): Promise<QueryResponse> {
  return apiFetch<QueryResponse>("/api/query", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/**
 * Liveness probe — resolves when the API server is reachable.
 */
export async function getHealth(): Promise<HealthResponse> {
  return apiFetch<HealthResponse>("/api/health");
}
