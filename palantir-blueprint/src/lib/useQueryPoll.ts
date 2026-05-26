// React hook: submits a query to /api/match (synchronous) and builds KG from response.

import { useCallback, useRef, useState } from "react";
import { matchQuery, fetchSubgraph, fetchSynthesis } from "./api";
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
  const [synthesis, setSynthesis] = useState<string | null>(null);
  const [synthesisLoading, setSynthesisLoading] = useState(false);

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
    setSynthesis(null);
    setSynthesisLoading(false);

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

      // Fire synthesis and subgraph enrichment in parallel (both non-fatal)
      setSynthesisLoading(true);

      // Prefer head entity from graph facts (always populated when Neo4j has data);
      // fall back to inline evidence and then to the first meaningful query keyword.
      const _factHeadRe = /^(.+?)\s+--\[/;
      const topEntity =
        (res.graphFacts[0] ? _factHeadRe.exec(res.graphFacts[0].trim())?.[1]?.trim() : undefined) ??
        res.matches[0]?.evidence[0]?.head ??
        query.trim().split(/\s+/).find((w) => w.length > 3);

      const [synthResult] = await Promise.allSettled([
        fetchSynthesis(query, res.matches),
        topEntity
          ? fetchSubgraph(topEntity).then((sub) => {
              if (abort.signal.aborted || sub.nodes.length === 0) return;
              const nodes = sub.nodes.map((n, i) => adaptSubgraphNode(n, i, sub.nodes.length));
              const edges = sub.links.map(adaptSubgraphLink);
              setGraph({ nodes, edges });
            }).catch(() => { /* Neo4j non-fatal */ })
          : Promise.resolve(),
      ]);

      if (!abort.signal.aborted) {
        setSynthesisLoading(false);
        if (synthResult.status === "fulfilled") {
          setSynthesis(synthResult.value.synthesis);
        }
        // synthesis failure is silent — card stays in "no response" state
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
    setSynthesis(null);
    setSynthesisLoading(false);
  }

  return { queryState, results, graph, meta, errorMsg, synthesis, synthesisLoading, runQuery, resetQuery };
}
