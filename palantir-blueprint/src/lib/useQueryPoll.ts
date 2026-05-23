// React hook: submits a query to /api/match (synchronous) and builds KG from response.

import { useCallback, useRef, useState } from "react";
import { matchQuery, fetchSubgraph } from "./api";
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
  runQuery: (query: string, options?: RunQueryOptions) => void;
  resetQuery: () => void;
}

interface RunQueryOptions {
  topK?: number;
}

export function useQueryPoll(): UseQueryPollResult {
  const [queryState, setQueryState] = useState<QueryState>("idle");
  const [results, setResults] = useState<TrialResult[]>([]);
  const [graph, setGraph] = useState<{ nodes: GraphNode[]; edges: GraphEdge[] } | null>(null);
  const [meta, setMeta] = useState<QueryMeta | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Abort controller so a new query can cancel an in-flight one
  const abortRef = useRef<AbortController | null>(null);

  const runQuery = useCallback(async (query: string, options: RunQueryOptions = {}) => {
    abortRef.current?.abort();
    const abort = new AbortController();
    abortRef.current = abort;

    setQueryState("loading");
    setResults([]);
    setGraph(null);
    setMeta(null);
    setErrorMsg(null);

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

      // Build KG immediately from inline evidence — no extra API call required
      const inlineGraph = adaptGraphFromMatch(res.graphFacts, res.matches);
      if (inlineGraph.nodes.length > 0) {
        setGraph(inlineGraph);
      }

      // Optionally enrich with Neo4j subgraph for the most prominent entity
      const topEntity = res.matches[0]?.evidence[0]?.head;
      if (topEntity && !abort.signal.aborted) {
        fetchSubgraph(topEntity)
          .then((sub) => {
            if (abort.signal.aborted || sub.nodes.length === 0) return;
            const nodes = sub.nodes.map((n, i) => adaptSubgraphNode(n, i, sub.nodes.length));
            const edges = sub.links.map(adaptSubgraphLink);
            setGraph({ nodes, edges });
          })
          .catch(() => {
            // Neo4j subgraph is non-fatal — inline KG already shown
          });
      }
    } catch (err) {
      if (abort.signal.aborted) return;
      setQueryState("error");
      setErrorMsg(err instanceof Error ? err.message : String(err));
    }
  }, []);

  function resetQuery() {
    abortRef.current?.abort();
    setQueryState("idle");
    setResults([]);
    setGraph(null);
    setMeta(null);
    setErrorMsg(null);
  }

  return { queryState, results, graph, meta, errorMsg, runQuery, resetQuery };
}
