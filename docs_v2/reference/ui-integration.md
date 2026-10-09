# Clinical Ops — Mockup Integration Reference

This document defines the data contracts, API shapes, and component integration points for replacing all mock data in the UI with live backend responses.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Query & Results Pane](#query--results-pane)
   - [POST /query](#post-query)
   - [TrialResult shape](#trialresult-shape)
   - [ProvenanceSource shape](#provenancesource-shape)
   - [Knowledge Graph data](#knowledge-graph-data)
3. [Ingestion Pipeline Pane](#ingestion-pipeline-pane)
   - [POST /ingest](#post-ingest)
   - [SSE event stream](#sse-event-stream)
   - [GET /ocr-debug/:jobId](#get-ocr-debugjobid)
   - [GET /chunks/:jobId](#get-chunksjobid)
4. [Shared types](#shared-types)
5. [State machine per pane](#state-machine-per-pane)
6. [Environment & config](#environment--config)
7. [Mock data removal checklist](#mock-data-removal-checklist)

---

## Architecture Overview

```
Browser
├── QueryPane          → REST: POST /query
│   ├── ResultsPanel   → response.results[]
│   ├── ProvenancePanel → response.results[n].provenances[]
│   └── KnowledgeGraph → response.graph { nodes[], edges[] }
└── IngestionPane      → REST: POST /ingest  (returns jobId)
    ├── PipelineSteps  → SSE: GET /ingest/stream/:jobId
    ├── OcrDebugViz    → REST: GET /ocr-debug/:jobId
    ├── ChunkCards     → REST: GET /chunks/:jobId
    └── CleanedMarkdown→ REST: GET /chunks/:jobId (field: cleanedMarkdown)
```

All endpoints share a base URL injected via `VITE_API_BASE_URL` (see [Environment & config](#environment--config)).

---

## Query & Results Pane

### POST /query

**File:** `src/components/QueryPane.tsx`  
**Trigger:** User presses RUN or hits Enter in the query input.

#### Request

```typescript
interface QueryRequest {
  query: string;
  filters?: {
    phase?:    string[];   // e.g. ["Phase 2", "Phase 3"]
    status?:   string[];   // e.g. ["Recruiting"]
    strategy?: string[];   // e.g. ["BM25 + Dense", "Dense"]
  };
  topK?: number;           // default: 10 — front-end currently shows 3, loads 2 more at a time
}
```

#### Response

```typescript
interface QueryResponse {
  results:  TrialResult[];
  graph:    GraphPayload;
  meta: {
    latencyMs:  number;
    indexVersion: string;   // e.g. "v19"
    strategy:   string;     // e.g. "RRF(BM25,DENSE)"
    totalHits:  number;
  };
}
```

HTTP status mapping:

| Status | UI state rendered |
|--------|-------------------|
| 200    | `"results"` tab with result cards |
| 200 with `results: []` | `"empty"` NonIdealState |
| 4xx / 5xx | `"error"` Callout with retry button |

---

### TrialResult shape

**File:** `src/components/QueryPane.tsx` — interface `TrialResult`

```typescript
interface TrialResult {
  id:               number | string;  // unique per response — used as React key
  nct:              string;           // NCT number, e.g. "NCT04371640"
  title:            string;
  phase:            string;           // "Phase 2" | "Phase 3" | "N/A" | ...
  sponsor:          string;
  enrollmentStatus: string;           // "Recruiting" | "Active, not recruiting" | "Completed"
  matchScore:       number;           // 0.0–1.0 — drives score badge intent
  strategy:         string;           // "BM25 + Dense" | "Dense" | "BM25"
  matchedCriteria:  string[];         // short label strings shown as primary tags
  source:           string;           // source document filename
  location:         string;           // human-readable offset, e.g. "§4.2 — bytes 18432–18891"
  snippet:          string;           // plain-text excerpt (~2 sentences)
  provenances:      ProvenanceSource[];
}
```

Score → badge intent mapping (already in code, do not change):
- `≥ 0.90` → `Intent.SUCCESS` (green)
- `≥ 0.80` → `Intent.WARNING` (amber)
- `< 0.80` → `Intent.DANGER` (red)

Enrollment status → badge intent:
- `"Recruiting"` → `Intent.SUCCESS`
- `"Completed"` → `Intent.NONE`
- everything else → `Intent.WARNING`

---

### ProvenanceSource shape

Rendered inside the expanded result card and in the standalone **PROVENANCE** tab.

```typescript
interface ProvenanceSource {
  source:    string;   // filename
  byteRange: string;   // "18432–18891"
  page:      string;   // "4 of 62" — use "N/A" for non-paginated sources
  conf:      number;   // 0.0–1.0 — drives highlight color and conf badge

  // Reconstructed context around the retrieved span.
  // The UI renders: preText + spans[0].highlight.text + spans[0].after + ...
  preText: string;
  spans: Array<{
    highlight: {
      text: string;
      conf: number;   // per-span confidence, may differ from parent conf
    };
    after: string;    // text that follows this highlight, up to the next span
  }>;
}
```

Highlight color thresholds (in `confHighlightStyle()` — do not change):
- `conf ≥ 0.90` → blue underline (`#4a7fa5`)
- `conf ≥ 0.80` → amber underline (`#9b7a2a`)
- `conf < 0.80` → red underline (`#8b3535`)

---

### Knowledge Graph data

**File:** `src/components/KnowledgeGraph.tsx`

The graph is currently rendered from static data (`INITIAL_NODES`, `EDGES`). Replace these constants with the `graph` field from the query response.

```typescript
interface GraphPayload {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

interface GraphNode {
  id:       string;          // unique, used as drag-state key and edge reference
  label:    string;
  sublabel?: string;         // shown inside node circle (e.g. "dx", "rx", "trial")
  type:     NodeType;        // "patient" | "condition" | "medication" | "lab" | "trial" | "relation"
  x:        number;          // initial SVG x position — backend provides a layout suggestion
  y:        number;          // initial SVG y position
  nctId?:   string;          // present on trial nodes — enables jump-to-result cross-link
}

interface GraphEdge {
  from:  string;   // node id
  to:    string;   // node id
  label: string;   // relationship label, e.g. "has_dx", "contraindicated_with"
}
```

Integration note: the graph is **interactive** (nodes draggable, click-to-select). Backend layout coordinates are used as _initial_ positions only — the user's drag state is local. Do not re-seed positions on every query response; only seed on first mount or explicit reset.

Clicking a `trial` node calls `onTrialClick(nctId)` which switches the tab to RESULTS and highlights the matching result card with a purple outline. This wiring is already in place.

---

## Ingestion Pipeline Pane

### POST /ingest

**File:** `src/components/IngestionPane.tsx`  
**Trigger:** User presses "Start Ingestion."

#### Request

```typescript
interface IngestRequest {
  fileUrl?:    string;   // pre-signed URL or internal path
  fileBase64?: string;   // alternative: raw bytes encoded as base64
  filename:    string;   // used for display in the event log
  options?: {
    ocrEngine?:      string;  // default: "tesseract-5.3"
    chunkStrategy?:  string;  // default: "sentence-window"
    chunkSize?:      number;  // default: 512
    chunkOverlap?:   number;  // default: 64
    embeddingModel?: string;  // default: "text-embedding-3-large"
  };
}
```

#### Response

```typescript
interface IngestResponse {
  jobId: string;   // used to open the SSE stream and fetch results
}
```

---

### SSE event stream

**File:** `src/components/IngestionPane.tsx` — `startIngestion()` function

Replace the `setTimeout` schedule with a real `EventSource`:

```typescript
const es = new EventSource(`${API_BASE}/ingest/stream/${jobId}`);
es.onmessage = (e) => {
  const event: PipelineEvent = JSON.parse(e.data);
  handlePipelineEvent(event);
};
es.onerror = () => { /* set step to "failed" */ };
```

#### PipelineEvent shape

```typescript
type PipelineEventType =
  | "log"
  | "step_start"
  | "step_progress"
  | "step_done"
  | "step_failed"
  | "complete";

interface PipelineEvent {
  type:       PipelineEventType;
  timestamp:  string;           // ISO-8601
  message?:   string;           // shown in the SSE event log Pre element

  // present on step_* events:
  stepIndex?: number;           // 0=OCR, 1=Chunking, 2=Markdown, 3=Embedding
  progress?:  number;           // 0.0–1.0

  // present on step_failed:
  errorMsg?:  string;           // shown below the failed step's progress bar

  // present on complete:
  summary?: {
    totalChunks:     number;
    totalVectors:    number;
    avgOcrConf:      number;
    artifactsRemoved: number;
  };
}
```

Step index → step name mapping (matches `INITIAL_STEPS` order in code):

| Index | Name |
|-------|------|
| 0 | OCR Processing |
| 1 | Text Chunking |
| 2 | Markdown Cleaning |
| 3 | Embedding & Indexing |

---

### GET /ocr-debug/:jobId

**File:** `src/components/IngestionPane.tsx` — `OcrDebugViz` component  
Fetch once after OCR step completes (`stepIndex: 0, type: "step_done"`).

#### Response

```typescript
interface OcrDebugResponse {
  page:   number;
  total:  number;   // total pages — shown in the subtitle label
  boxes: Array<{
    top:    number;   // SVG/CSS absolute position in px (viewBox: 0 0 460 175)
    left:   number;
    width:  number;
    height: number;
    label:  string;   // OCR-read text for this bounding box
    conf:   "high" | "medium" | "low";
  }>;
  heatmap: number[][];   // rows × cols grid of confidence values 0.0–1.0
                         // currently rendered at 6 columns, any row count accepted
}
```

The UI toggle **BOXES / HEATMAP** is already wired to `ocrMode` state — no backend change needed.

---

### GET /chunks/:jobId

**File:** `src/components/IngestionPane.tsx` — `ChunkCard` + `MarkdownDiff` components  
Fetch once after `type: "complete"` event fires.

#### Response

```typescript
interface ChunksResponse {
  chunks: Chunk[];
  rawOcrText:      string;   // shown in the DIFF view left panel
  cleanedMarkdown: string;   // shown in the DIFF view right panel and OUTPUT view
}

interface Chunk {
  id:         number;
  charRange:  [number, number];   // [start, end] byte offsets in cleaned text
  page:       number;
  tokenCount: number;
  text:       string;
  entities: Array<{
    text: string;
    type: "medication" | "condition" | "measurement" | "protocol";
  }>;
}
```

Entity type → color mapping (in `ENTITY_COLORS` — do not change):

| Type | Background | Text |
|------|-----------|------|
| `medication` | amber 18% | `#c49a3c` |
| `condition` | red 18% | `#b05555` |
| `measurement` | green 18% | `#5aaa78` |
| `protocol` | blue 18% | `#6a9bc0` |

Chunks are **editable** in the UI (textarea). If rechunking is supported, add a `PATCH /chunks/:jobId/:chunkId` endpoint. The component is already structured to support this.

---

## Shared types

Defined across both panes — keep these consistent when building the backend models:

```typescript
type NodeType = "patient" | "condition" | "medication" | "lab" | "trial" | "relation";

type StepStatus = "idle" | "active" | "done" | "failed";

type QueryState = "idle" | "loading" | "results" | "error" | "empty";
```

---

## State machine per pane

### QueryPane

```
idle ──[run query]──► loading ──[200 + results]──► results
                              └──[200 + empty ]──► empty
                              └──[4xx/5xx    ]──► error
error ──[retry]──► loading
results ──[run query]──► loading
```

The `queryState` variable drives: skeleton cards (loading), NonIdealState (idle/empty), Callout (error), result cards (results).

### IngestionPane

```
idle ──[start]──► running ──[complete event]──► done
running ──[cancel]──► idle
done ──[re-run]──► running
```

Individual step statuses follow: `idle → active → done | failed`  
A `failed` step stops SSE consumption and shows an inline error message under that step's progress bar.

---

## Environment & config

Add the following to `.env.local` (not committed):

```
VITE_API_BASE_URL=http://localhost:8000
```

Usage in components:

```typescript
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";
```

All fetch calls should use this base. The mockup currently has no fetch calls — the integration point is the start of `runQuery()` in `QueryPane.tsx` and `startIngestion()` in `IngestionPane.tsx`.

---

## Mock data removal checklist

When integrating the backend, replace these constants in order:

### QueryPane.tsx

- [ ] `TRIAL_RESULTS` — replace with `response.results` from `POST /query`
- [ ] `FILTER_OPTIONS` — optionally fetch from `GET /query/filters` to keep dynamic
- [ ] Status bar values (`RESULTS`, `LATENCY`, `INDEX`, `STRATEGY`) — populate from `response.meta`
- [ ] Hardcoded `1400ms` delay in `runQuery()` — remove `setTimeout`, wire real fetch

### KnowledgeGraph.tsx

- [ ] `INITIAL_NODES` + `EDGES` — replace with `response.graph.nodes` and `response.graph.edges` from `POST /query`
- [ ] Pass graph data in as props from `QueryPane` rather than importing constants

### IngestionPane.tsx

- [ ] `SSE_LOG_LINES` + `setTimeout` schedule — replace with real `EventSource` on `jobId`
- [ ] `OCR_BOXES` + `HEATMAP_GRID` — replace with `GET /ocr-debug/:jobId` response
- [ ] `MOCK_CHUNKS` — replace with `GET /chunks/:jobId` response
- [ ] `RAW_OCR_TEXT` + `CLEANED_MARKDOWN` — replace with `chunksResponse.rawOcrText` and `chunksResponse.cleanedMarkdown`
- [ ] `INITIAL_STEPS` — names are fixed but `status` / `progress` are driven by SSE events already; no change needed to the step-rendering logic
