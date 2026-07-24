// React hook: submits a query to /api/match (synchronous) and builds KG from response.

import { useCallback, useRef, useState } from "react";
import { ApiError, fetchSubgraph, fetchSynthesis, matchQuery } from "./api";
import type { BackendMatch } from "./api";
import { adaptResult, adaptGraphFromMatch, adaptSubgraphNode, adaptSubgraphLink } from "./adapters";
import type { TrialResult, GraphNode, GraphEdge } from "./adapters";

export type QueryState = "idle" | "loading" | "results" | "error" | "empty";

interface QueryMeta {
  latencyMs: number;
  indexVersion: string;
  strategy: string;
  totalHits: number;
}

interface UseQueryPollResult {
  queryState: QueryState;
  results: TrialResult[];
  graph: { nodes: GraphNode[]; edges: GraphEdge[] } | null;
  meta: QueryMeta | null;
  errorMsg: string | null;
  synthesis: string | null;
  synthesisLoading: boolean;
  synthesisError: ApiError | null;
  synthesisModel: string | null;
  synthesisFallbackUsed: boolean;
  runQuery: (query: string, options?: RunQueryOptions) => void;
  retrySynthesis: () => void;
  resetQuery: () => void;
}

interface RunQueryOptions {
  topK?: number;
}

interface SynthesisRequest {
  query: string;
  evidence: BackendMatch[];
  requestId: number;
}

function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error;
  return new ApiError(0, {
    code: null,
    message: "Synthesis could not be completed. Please try again.",
    retryable: true,
  });
}

export function useQueryPoll(): UseQueryPollResult {
  const [queryState, setQueryState] = useState<QueryState>("idle");
  const [results, setResults] = useState<TrialResult[]>([]);
  const [graph, setGraph] = useState<{ nodes: GraphNode[]; edges: GraphEdge[] } | null>(null);
  const [meta, setMeta] = useState<QueryMeta | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [synthesis, setSynthesis] = useState<string | null>(null);
  const [synthesisLoading, setSynthesisLoading] = useState(false);
  const [synthesisError, setSynthesisError] = useState<ApiError | null>(null);
  const [synthesisModel, setSynthesisModel] = useState<string | null>(null);
  const [synthesisFallbackUsed, setSynthesisFallbackUsed] = useState(false);

  // Abort controller so a new query can cancel an in-flight one
  const abortRef = useRef<AbortController | null>(null);
  const requestIdRef = useRef(0);
  const synthesisAttemptRef = useRef(0);
  const synthesisRequestRef = useRef<SynthesisRequest | null>(null);

  const runSynthesis = useCallback(async (request: SynthesisRequest) => {
    const attemptId = ++synthesisAttemptRef.current;
    setSynthesisLoading(true);
    setSynthesisError(null);
    setSynthesis(null);
    setSynthesisModel(null);
    setSynthesisFallbackUsed(false);

    try {
      const response = await fetchSynthesis(request.query, request.evidence);
      if (requestIdRef.current !== request.requestId || synthesisAttemptRef.current !== attemptId) return;

      setSynthesis(response.synthesis);
      setSynthesisModel(response.model);
      setSynthesisFallbackUsed(response.fallbackUsed);
    } catch (error) {
      if (requestIdRef.current !== request.requestId || synthesisAttemptRef.current !== attemptId) return;
      setSynthesisError(toApiError(error));
    } finally {
      if (requestIdRef.current === request.requestId && synthesisAttemptRef.current === attemptId) {
        setSynthesisLoading(false);
      }
    }
  }, []);

  const runQuery = useCallback(async (query: string, options: RunQueryOptions = {}) => {
    abortRef.current?.abort();
    const abort = new AbortController();
    abortRef.current = abort;
    const requestId = ++requestIdRef.current;
    synthesisRequestRef.current = null;

    setQueryState("loading");
    setResults([]);
    setGraph(null);
    setMeta(null);
    setErrorMsg(null);
    setSynthesis(null);
    setSynthesisLoading(false);
    setSynthesisError(null);
    setSynthesisModel(null);
    setSynthesisFallbackUsed(false);

    try {
      const res = await matchQuery(query, options.topK ?? 10);

      if (abort.signal.aborted) return;

      if (!res.found || res.matches.length === 0) {
        setQueryState("empty");
        setMeta({ latencyMs: res.latency_ms, indexVersion: "live", strategy: "GraphRAG", totalHits: 0 });
        return;
      }

      const adapted = res.matches.map(adaptResult);
      setResults(adapted);
      setMeta({
        latencyMs: res.latency_ms,
        indexVersion: "live",
        strategy: "GraphRAG + Dense",
        totalHits: adapted.length,
      });
      setQueryState("results");
      const synthesisRequest = { query, evidence: res.matches, requestId };
      synthesisRequestRef.current = synthesisRequest;

      // Build KG immediately from inline evidence — no extra API call required
      const inlineGraph = adaptGraphFromMatch(res.graphFacts, res.matches);
      if (inlineGraph.nodes.length > 0) {
        setGraph(inlineGraph);
      }

      void runSynthesis(synthesisRequest);

      if (res.graphAnchor) {
        void fetchSubgraph(res.graphAnchor)
          .then((sub) => {
            if (abort.signal.aborted || requestIdRef.current !== requestId || sub.nodes.length === 0) return;
            const nodes = sub.nodes.map((n, i) => adaptSubgraphNode(n, i, sub.nodes.length));
            const edges = sub.links.map(adaptSubgraphLink);
            setGraph({ nodes, edges });
          })
          .catch(() => { /* Neo4j enrichment is non-fatal. */ });
      }
    } catch (err) {
      if (abort.signal.aborted) return;
      setQueryState("error");
      setErrorMsg(err instanceof Error ? err.message : String(err));
    }
  }, [runSynthesis]);

  const retrySynthesis = useCallback(() => {
    const request = synthesisRequestRef.current;
    if (request) void runSynthesis(request);
  }, [runSynthesis]);

  function resetQuery() {
    abortRef.current?.abort();
    requestIdRef.current += 1;
    synthesisAttemptRef.current += 1;
    synthesisRequestRef.current = null;
    setQueryState("idle");
    setResults([]);
    setGraph(null);
    setMeta(null);
    setErrorMsg(null);
    setSynthesis(null);
    setSynthesisLoading(false);
    setSynthesisError(null);
    setSynthesisModel(null);
    setSynthesisFallbackUsed(false);
  }

  return {
    queryState,
    results,
    graph,
    meta,
    errorMsg,
    synthesis,
    synthesisLoading,
    synthesisError,
    synthesisModel,
    synthesisFallbackUsed,
    runQuery,
    retrySynthesis,
    resetQuery,
  };
}
