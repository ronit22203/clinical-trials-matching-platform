// React hook: submits a query, polls for results, and fetches the knowledge graph.

import { useCallback, useRef, useState } from "react";
import { submitQuery, fetchQueryResults, fetchKnowledgeGraph } from "./api";
import { adaptResult, adaptGraphNode, adaptGraphEdge } from "./adapters";
import type { TrialResult, GraphNode, GraphEdge } from "./adapters";

type QueryState = "idle" | "loading" | "results" | "error" | "empty";

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
  runQuery: (query: string, options?: RunQueryOptions) => void;
  resetQuery: () => void;
}

interface RunQueryOptions {
  topK?: number;
  filters?: { condition?: string; phase?: string; status?: string };
}

const POLL_INTERVAL_MS = 1000;
const POLL_TIMEOUT_MS = 30_000;

export function useQueryPoll(): UseQueryPollResult {
  const [queryState, setQueryState] = useState<QueryState>("idle");
  const [results, setResults] = useState<TrialResult[]>([]);
  const [graph, setGraph] = useState<{ nodes: GraphNode[]; edges: GraphEdge[] } | null>(null);
  const [meta, setMeta] = useState<QueryMeta | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startRef = useRef<number>(0);

  function clearPoll() {
    if (pollRef.current !== null) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }

  const runQuery = useCallback(
    async (query: string, options: RunQueryOptions = {}) => {
      clearPoll();
      setQueryState("loading");
      setResults([]);
      setGraph(null);
      setMeta(null);
      setErrorMsg(null);

      let queryId: string;
      const t0 = Date.now();
      startRef.current = t0;

      try {
        const submitted = await submitQuery(query, { topK: options.topK ?? 10, filters: options.filters });
        queryId = submitted.query_id;
      } catch (err) {
        setQueryState("error");
        setErrorMsg(err instanceof Error ? err.message : String(err));
        return;
      }

      pollRef.current = setInterval(async () => {
        const elapsed = Date.now() - startRef.current;
        if (elapsed > POLL_TIMEOUT_MS) {
          clearPoll();
          setQueryState("error");
          setErrorMsg("Query timed out after 30 seconds.");
          return;
        }

        try {
          const res = await fetchQueryResults(queryId);

          if (res.status === "failed") {
            clearPoll();
            setQueryState("error");
            setErrorMsg(res.error ?? "Query failed.");
            return;
          }

          if (res.status === "completed" && res.results !== null) {
            clearPoll();

            const latencyMs = Date.now() - t0;
            const adapted = res.results.map(adaptResult);

            setResults(adapted);
            setMeta({
              latencyMs,
              indexVersion: "live",
              strategy: adapted[0]?.strategy ?? "N/A",
              totalHits: adapted.length,
            });
            setQueryState(adapted.length > 0 ? "results" : "empty");

            // Fetch KG in background — non-blocking
            fetchKnowledgeGraph(queryId)
              .then((kg) => {
                const nodes = kg.nodes.map((n, i) => adaptGraphNode(n, i, kg.nodes.length));
                const edges = kg.edges.map(adaptGraphEdge);
                setGraph({ nodes, edges });
              })
              .catch(() => {
                // KG failure is non-fatal — leave graph as null
              });
          }
        } catch (err) {
          clearPoll();
          setQueryState("error");
          setErrorMsg(err instanceof Error ? err.message : String(err));
        }
      }, POLL_INTERVAL_MS);
    },
    []
  );

  function resetQuery() {
    clearPoll();
    setQueryState("idle");
    setResults([]);
    setGraph(null);
    setMeta(null);
    setErrorMsg(null);
  }

  return { queryState, results, graph, meta, errorMsg, runQuery, resetQuery };
}
