// Normalizes backend API response shapes into the UI's expected interface shapes.

import type {
  BackendMatch,
  BackendMatchEvidence,
  BackendSubgraphNode,
  BackendSubgraphLink,
  BackendChunk,
} from "./api";

// ─── UI types ──────────────────────────────────────────────────

export type NodeType = "patient" | "condition" | "medication" | "lab" | "trial" | "relation";

export interface ProvenanceSpan {
  text: string;
  conf: number;
}

export interface ProvenanceSource {
  source: string;
  byteRange: string;
  page: string;
  conf: number;
  preText: string;
  spans: Array<{ highlight: ProvenanceSpan; after: string }>;
}

export interface TrialResult {
  id: string | number;
  nct: string;
  title: string;
  phase: string;
  sponsor: string;
  enrollmentStatus: string;
  matchScore: number;
  strategy: string;
  matchedCriteria: string[];
  source: string;
  location: string;
  snippet: string;
  provenances: ProvenanceSource[];
}

export interface GraphNode {
  id: string;
  label: string;
  sublabel?: string;
  type: NodeType;
  x: number;
  y: number;
  nctId?: string;
}

export interface GraphEdge {
  from: string;
  to: string;
  label: string;
}

export interface OcrBox {
  top: number;
  left: number;
  width: number;
  height: number;
  label: string;
  conf: "high" | "medium" | "low";
}

export interface UIChunkEntity {
  text: string;
  type: "medication" | "condition" | "measurement" | "protocol";
}

export interface UIChunk {
  id: number;
  charRange: [number, number];
  page: number;
  tokenCount: number;
  text: string;
  entities: UIChunkEntity[];
}

// ─── KG layout helper ─────────────────────────────────────────

function circularLayout(count: number, index: number): { x: number; y: number } {
  if (count === 1) return { x: 230, y: 217 };
  const cx = 230;
  const cy = 200;
  const r = Math.min(160, 60 + count * 18);
  const angle = (2 * Math.PI * index) / count - Math.PI / 2;
  return {
    x: Math.round(cx + r * Math.cos(angle)),
    y: Math.round(cy + r * Math.sin(angle)),
  };
}

// ─── Result adapter (BackendMatch from /api/match) ─────────────

function adaptEvidence(ev: BackendMatchEvidence, score: number): ProvenanceSource {
  return {
    source: ev.source,
    byteRange: `${ev.byteStart}–${ev.byteEnd}`,
    page: "N/A",
    conf: score,
    preText: "",
    spans: [
      {
        highlight: {
          text: `${ev.head} ${ev.relation} ${ev.tail}`,
          conf: score,
        },
        after: "",
      },
    ],
  };
}

export function adaptResult(match: BackendMatch, index: number): TrialResult {
  const firstEv = match.evidence[0];
  // Use the first triplet head as the "NCT ID" placeholder — most meaningful available identifier
  const nct = firstEv?.head ?? `CHUNK-${match.chunkIndex}`;
  // Extract a title from context breadcrumb or fall back to content prefix
  const title = match.context
    ? match.context.replace(/^Context:\s*/i, "").replace(/\n+.*$/s, "").trim()
    : match.content.slice(0, 100).trimEnd();

  return {
    id: index,
    nct,
    title: title || `Result ${index + 1}`,
    phase: "N/A",
    sponsor: "N/A",
    enrollmentStatus: "N/A",
    matchScore: match.score,
    strategy: "GraphRAG + Dense",
    matchedCriteria: match.evidence.map((e) => `${e.head} → ${e.tail}`),
    source: match.source,
    location: match.source,
    snippet: match.content,
    provenances: match.evidence.length > 0
      ? match.evidence.map((e) => adaptEvidence(e, match.score))
      : [],
  };
}

// ─── KG adapter: build graph from match evidence + graphFacts ──

const GRAPH_FACT_RE = /^(.+?)\s+--\[(.+?)\]-->\s+(.+)$/;

const TIER_TYPE_MAP: Record<number, NodeType> = {
  1: "condition",
  2: "medication",
};

function ensureNode(
  nodeMap: Map<string, GraphNode>,
  id: string,
  tier: number
): void {
  if (nodeMap.has(id)) return;
  const type: NodeType = TIER_TYPE_MAP[tier] ?? "relation";
  const sublabelMap: Partial<Record<NodeType, string>> = {
    condition: "entity",
    medication: "rx",
    lab: "lab",
    trial: "trial",
  };
  nodeMap.set(id, {
    id,
    label: id,
    sublabel: sublabelMap[type],
    type,
    x: 0,
    y: 0,
  });
}

export function adaptGraphFromMatch(
  graphFacts: string[],
  matches: BackendMatch[]
): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const nodeMap = new Map<string, GraphNode>();
  const edgeSet = new Set<string>();
  const edges: GraphEdge[] = [];

  function addEdge(from: string, to: string, label: string, headTier = 1, tailTier = 2) {
    ensureNode(nodeMap, from, headTier);
    ensureNode(nodeMap, to, tailTier);
    const key = `${from}|${to}|${label}`;
    if (!edgeSet.has(key)) {
      edgeSet.add(key);
      edges.push({ from, to, label });
    }
  }

  // Parse graphFacts strings: "head --[relation]--> tail"
  for (const fact of graphFacts) {
    const m = GRAPH_FACT_RE.exec(fact.trim());
    if (!m) continue;
    addEdge(m[1].trim(), m[3].trim(), m[2].trim());
  }

  // Supplement with inline evidence triplets
  for (const match of matches) {
    for (const ev of match.evidence) {
      addEdge(ev.head, ev.tail, ev.relation, ev.tier, ev.tier + 1);
    }
  }

  const nodes = [...nodeMap.values()];
  nodes.forEach((n, i) => {
    const pos = circularLayout(nodes.length, i);
    n.x = pos.x;
    n.y = pos.y;
  });

  return { nodes, edges };
}

// ─── Subgraph adapter (GET /api/debug/subgraph/{entity}) ───────

export function adaptSubgraphNode(
  node: BackendSubgraphNode,
  index: number,
  total: number
): GraphNode {
  const { x, y } = circularLayout(total, index);
  const type: NodeType = node.tier === 1 ? "condition" : "medication";
  return {
    id: node.id,
    label: node.label,
    type,
    x,
    y,
  };
}

export function adaptSubgraphLink(link: BackendSubgraphLink): GraphEdge {
  return { from: link.source, to: link.target, label: link.relation };
}

// ─── Chunk adapter ────────────────────────────────────────────

export function adaptChunk(chunk: BackendChunk, index: number): UIChunk {
  return {
    id: index + 1,
    charRange: [chunk.char_start, chunk.char_end],
    page: (chunk.metadata.page_number as number | undefined) ?? 1,
    tokenCount: (chunk.metadata.token_count as number | undefined) ?? 0,
    text: chunk.text,
    entities: [],
  };
}
