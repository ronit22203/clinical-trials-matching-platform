// Normalizes backend API response shapes into the UI's expected interface shapes.

import type {
  BackendResult,
  BackendProvenance,
  BackendKGNode,
  BackendKGEdge,
  BackendOCRPage,
  BackendChunk,
} from "./api";

// ─── UI types (duplicated here to avoid circular imports) ──────
// These match the interfaces declared inside QueryPane.tsx / IngestionPane.tsx / KnowledgeGraph.tsx

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

// ─── KG node type mapping ──────────────────────────────────────

const KG_TYPE_MAP: Record<BackendKGNode["type"], NodeType> = {
  trial: "trial",
  condition: "condition",
  intervention: "medication",
  outcome: "lab",
  document: "relation",
};

// Simple force-layout seed: arrange nodes in a circle within 460×435 viewBox
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

export function adaptGraphNode(node: BackendKGNode, index: number, total: number): GraphNode {
  const { x, y } = circularLayout(total, index);
  const type = KG_TYPE_MAP[node.type] ?? "relation";
  const sublabelMap: Partial<Record<NodeType, string>> = {
    condition: "dx",
    medication: "rx",
    lab: "lab",
    trial: "trial",
  };
  return {
    id: node.id,
    label: node.label,
    sublabel: sublabelMap[type],
    type,
    x,
    y,
    nctId: node.type === "trial" ? node.label : undefined,
  };
}

export function adaptGraphEdge(edge: BackendKGEdge): GraphEdge {
  return { from: edge.source, to: edge.target, label: edge.label };
}

// ─── Provenance adapter ────────────────────────────────────────

export function adaptProvenance(prov: BackendProvenance): ProvenanceSource {
  const [start, end] = prov.byte_range;
  return {
    source: prov.source_document,
    byteRange: `${start}–${end}`,
    page: "N/A",
    conf: prov.confidence_score,
    preText: "",
    spans: [
      {
        highlight: { text: prov.highlighted_text, conf: prov.confidence_score },
        after: "",
      },
    ],
  };
}

// ─── TrialResult adapter ───────────────────────────────────────

export function adaptResult(result: BackendResult): TrialResult {
  const meta = result.metadata ?? {};
  const firstProv = result.provenance[0];
  const location = firstProv
    ? `bytes ${firstProv.byte_range[0]}–${firstProv.byte_range[1]}`
    : "N/A";

  return {
    id: result.id,
    nct: result.trial_id,
    title: result.title,
    phase: (meta.phase as string | undefined) ?? "N/A",
    sponsor: (meta.sponsor as string | undefined) ?? "N/A",
    enrollmentStatus: (meta.enrollment_status as string | undefined) ?? "N/A",
    matchScore: result.relevance_score,
    strategy: (meta.strategy as string | undefined) ?? "Dense",
    matchedCriteria: result.matched_criteria,
    source: firstProv?.source_document ?? "N/A",
    location,
    snippet: result.snippet,
    provenances: result.provenance.map(adaptProvenance),
  };
}

// ─── OCR adapter ──────────────────────────────────────────────

// Target viewBox for the OcrDebugViz component
const OCR_VIEW_W = 460;
const OCR_VIEW_H = 175;

function confidenceLabel(conf: number): "high" | "medium" | "low" {
  if (conf >= 0.85) return "high";
  if (conf >= 0.65) return "medium";
  return "low";
}

export function adaptOcrBoxes(page: BackendOCRPage): OcrBox[] {
  if (!page || page.blocks.length === 0) return [];
  const scaleX = OCR_VIEW_W / (page.width || OCR_VIEW_W);
  const scaleY = OCR_VIEW_H / (page.height || OCR_VIEW_H);
  return page.blocks.map((block) => {
    const [x0, y0, x1, y1] = block.bbox;
    return {
      top: Math.round(y0 * scaleY),
      left: Math.round(x0 * scaleX),
      width: Math.round((x1 - x0) * scaleX),
      height: Math.round((y1 - y0) * scaleY),
      label: block.text,
      conf: confidenceLabel(block.confidence),
    };
  });
}

export function adaptOcrHeatmap(page: BackendOCRPage, cols = 6): number[][] {
  if (!page || page.blocks.length === 0) return [];
  const confidences = page.blocks.map((b) => b.confidence);
  const rowCount = Math.ceil(confidences.length / cols);
  const grid: number[][] = [];
  for (let r = 0; r < rowCount; r++) {
    const row: number[] = [];
    for (let c = 0; c < cols; c++) {
      const idx = r * cols + c;
      row.push(idx < confidences.length ? confidences[idx] : 1.0);
    }
    grid.push(row);
  }
  return grid;
}

// ─── Chunk adapter ────────────────────────────────────────────

export function adaptChunk(chunk: BackendChunk, index: number): UIChunk {
  return {
    id: index + 1,
    charRange: [chunk.char_start, chunk.char_end],
    page: (chunk.metadata.page_number as number | undefined) ?? 1,
    tokenCount: (chunk.metadata.token_count as number | undefined) ?? 0,
    text: chunk.text,
    // TODO: wire entity extraction once backend provides NER output
    entities: [],
  };
}
