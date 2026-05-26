import { useEffect, useRef, useState } from "react";
import {
  Button,
  Card,
  Classes,
  Divider,
  Elevation,
  H4,
  H5,
  Icon,
  Intent,
  NonIdealState,
  Pre,
  ProgressBar,
  Spinner,
  Tag,
} from "@blueprintjs/core";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/TextLayer.css";
import "react-pdf/dist/Page/AnnotationLayer.css";
import { startIngestStream, fetchChunks, fetchMarkdownArtifact, fetchCleanArtifact, getOcrVizUrl } from "../lib/api";
import { adaptChunk } from "../lib/adapters";
import type { UIChunk } from "../lib/adapters";

// Share the same worker config as QueryPane (idempotent assignment)
pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url,
).toString();

// ─── Types ────────────────────────────────────────────────────

type StepStatus = "idle" | "active" | "done" | "failed";
type MarkdownView = "output" | "diff";

interface PipelineStep {
  name: string;
  clinicianName: string;
  progress: number;
  status: StepStatus;
  errorMsg?: string;
}

// Chunk and ChunkEntity are imported as UIChunk from ../lib/adapters
type Chunk = UIChunk;
type ChunkEntity = UIChunk["entities"][number];

// ─── Mock data ────────────────────────────────────────────────

const INITIAL_STEPS: PipelineStep[] = [
  { name: "OCR Processing",       clinicianName: "Reading document",           progress: 0, status: "idle" },
  { name: "Text Chunking",        clinicianName: "Extracting medical terms",   progress: 0, status: "idle" },
  { name: "Markdown Cleaning",    clinicianName: "Organizing content",         progress: 0, status: "idle" },
  { name: "Embedding & Indexing", clinicianName: "Building knowledge graph",   progress: 0, status: "idle" },
];

// Word-level OCR bounding boxes
// Heatmap grid — 6 columns × 9 rows of simulated confidence values
const ENTITY_COLORS: Record<ChunkEntity["type"], { bg: string; text: string }> = {
  medication:  { bg: "rgba(181,137,0,0.12)",   text: "#8a6800" },
  condition:   { bg: "rgba(203,75,22,0.12)",   text: "#b53a10" },
  measurement: { bg: "rgba(42,161,152,0.12)",  text: "#1d8a83" },
  protocol:    { bg: "rgba(38,139,210,0.12)",  text: "#1a6fa8" },
};

// ─── Sub-components ───────────────────────────────────────────

function OcrDebugViz({
  vizUrl,
  page,
  pageCount,
  onPageChange,
}: {
  vizUrl: string | null;
  page: number;
  pageCount: number;
  onPageChange: (p: number) => void;
}) {
  if (!vizUrl) {
    return (
      <Card elevation={Elevation.ONE} style={{ height: 175, display: "flex", alignItems: "center", justifyContent: "center", background: "var(--surface-2)", borderRadius: 6 }}>
        <span style={{ fontFamily: "var(--text-mono)", fontSize: 10, color: "var(--text-dim)" }}>OCR debug visualization available after ingestion completes</span>
      </Card>
    );
  }
  return (
    <>
      <Card
        elevation={Elevation.ONE}
        style={{ height: 175, overflow: "hidden", background: "var(--surface-2)", borderRadius: 6, display: "flex", alignItems: "center", justifyContent: "center" }}
      >
        <img
          src={vizUrl}
          alt="OCR debug visualization — bounding boxes overlaid on page"
          style={{ maxHeight: 175, maxWidth: "100%", objectFit: "contain" }}
          onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
        />
      </Card>
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 6 }}>
        <Button
          minimal small icon="chevron-left" disabled={page <= 1}
          onClick={() => onPageChange(page - 1)}
          style={{ minWidth: 24 }}
        />
        <span style={{ fontFamily: "var(--text-mono)", fontSize: 10, color: "var(--text-dim)", flex: 1 }}>
          Surya OCR bounding-box overlay — page {page} / {pageCount}
        </span>
        <Button
          minimal small icon="chevron-right" disabled={page >= pageCount}
          onClick={() => onPageChange(page + 1)}
          style={{ minWidth: 24 }}
        />
      </div>
    </>
  );
}

function ChunkCard({ chunk, clinicianMode }: { chunk: Chunk; clinicianMode: boolean }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <Card elevation={Elevation.ONE} style={{ padding: "8px 12px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <Tag minimal intent={Intent.PRIMARY} style={{ fontFamily: "var(--text-mono)", fontSize: 10 }}>
            chunk {chunk.id}
          </Tag>
          <Tag minimal style={{ fontFamily: "var(--text-mono)", fontSize: 10 }}>
            p.{chunk.page}
          </Tag>
          {!clinicianMode && (
            <>
              <Tag minimal style={{ fontFamily: "var(--text-mono)", fontSize: 10 }}>
                [{chunk.charRange[0]}:{chunk.charRange[1]}]
              </Tag>
              <Tag minimal intent={Intent.NONE} style={{ fontFamily: "var(--text-mono)", fontSize: 10 }}>
                {chunk.tokenCount} tok
              </Tag>
            </>
          )}
        </div>
        <Button
          minimal
          small
          icon={expanded ? "chevron-up" : "chevron-down"}
          onClick={() => setExpanded((v) => !v)}
        />
      </div>

      {/* Entity tags */}
      <div style={{ display: "flex", gap: 5, flexWrap: "wrap", marginBottom: expanded ? 8 : 0 }}>
        {chunk.entities.map((ent) => (
          <Tag
            key={ent.text}
            minimal
            style={{
              fontSize: 10,
              background: ENTITY_COLORS[ent.type].bg,
              color: ENTITY_COLORS[ent.type].text,
            }}
          >
            {ent.text}
          </Tag>
        ))}
      </div>

      {expanded && (
        <textarea
          defaultValue={chunk.text}
          style={{
            width: "100%",
            marginTop: 4,
            background: "var(--surface-0)",
            border: "1px solid var(--border)",
            borderRadius: 2,
            color: "var(--text-secondary)",
            fontFamily: "var(--text-mono)",
            fontSize: 11,
            lineHeight: 1.65,
            padding: "6px 8px",
            resize: "vertical",
            minHeight: 72,
            outline: "none",
          }}
        />
      )}
    </Card>
  );
}

function MarkdownDiff({ rawOcrText, cleanedMarkdown }: { rawOcrText: string; cleanedMarkdown: string }) {
  if (!rawOcrText && !cleanedMarkdown) {
    return (
      <Card elevation={Elevation.ONE} style={{ padding: "10px 14px" }}>
        <span style={{ fontFamily: "var(--text-mono)", fontSize: 10, color: "var(--text-dim)" }}>
          Diff view available after ingestion completes.
        </span>
      </Card>
    );
  }
  return (
    <div style={{ display: "flex", gap: 8 }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="section-label" style={{ marginBottom: 5 }}>RAW OCR</div>
        <Pre
          style={{
            margin: 0,
            fontSize: 10.5,
            lineHeight: 1.7,
            whiteSpace: "pre-wrap",
            background: "var(--surface-0)",
            border: "1px solid var(--border)",
            color: "var(--text-dim)",
          }}
        >
          {rawOcrText}
        </Pre>
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="section-label" style={{ marginBottom: 5 }}>CLEANED</div>
        <Pre
          style={{
            margin: 0,
            fontSize: 10.5,
            lineHeight: 1.7,
            whiteSpace: "pre-wrap",
            background: "var(--surface-0)",
            border: "1px solid var(--border)",
            color: "var(--text-primary)",
          }}
        >
          {cleanedMarkdown.split("\n").map((line, i) => {
            const isAdded = line.startsWith("##") || line.startsWith("**") || line.startsWith(">");
            return (
              <span
                key={i}
                style={{
                  display: "block",
                  background: isAdded ? "rgba(42, 161, 152, 0.10)" : undefined,
                  borderLeft: isAdded ? "2px solid #2aa198" : "2px solid transparent",
                  paddingLeft: isAdded ? 4 : 6,
                }}
              >
                {line}
              </span>
            );
          })}
        </Pre>
      </div>
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────

/** Page-1 thumbnail + file metadata shown before ingestion starts. */
function PdfPreview({ file, onStart, clinicianMode }: { file: File; onStart: () => void; clinicianMode: boolean }) {
  const [pageCount, setPageCount] = useState<number | null>(null);
  return (
    <div className="pdf-preview-card">
      <div className="pdf-preview-thumb">
        <Document
          file={file}
          onLoadSuccess={({ numPages }) => setPageCount(numPages)}
          loading={
            <div style={{ width: 160, height: 210, display: "flex", alignItems: "center", justifyContent: "center", background: "var(--surface-2)" }}>
              <Spinner size={20} />
            </div>
          }
          error={
            <div style={{ width: 160, height: 210, display: "flex", alignItems: "center", justifyContent: "center", background: "var(--surface-2)", fontFamily: "var(--text-mono)", fontSize: 10, color: "var(--text-dim)" }}>
              No preview
            </div>
          }
        >
          <Page pageNumber={1} width={160} renderTextLayer={false} renderAnnotationLayer={false} />
        </Document>
      </div>
      <div style={{ textAlign: "center" }}>
        <div style={{ fontFamily: "var(--text-mono)", fontSize: 11, color: "var(--text-primary)", marginBottom: 3, maxWidth: 240, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {file.name}
        </div>
        <div style={{ fontFamily: "var(--text-mono)", fontSize: 10, color: "var(--text-dim)" }}>
          {(file.size / 1024).toFixed(0)} KB{pageCount != null ? ` · ${pageCount} page${pageCount !== 1 ? "s" : ""}` : ""}
        </div>
      </div>
      <Button intent={Intent.PRIMARY} icon={clinicianMode ? "upload" : "play"} onClick={onStart}>
        {clinicianMode ? "Upload & Process" : "Start Ingestion"}
      </Button>
    </div>
  );
}

/** Collapsed chunk summary. Audit view (engineer mode only) expands individual cards. */
function ChunkSummary({ chunks, clinicianMode }: { chunks: Chunk[]; clinicianMode: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const pages = chunks.map((c) => c.page).filter((p) => p > 0);
  const minPage = pages.length ? Math.min(...pages) : 1;
  const maxPage = pages.length ? Math.max(...pages) : 1;
  const pageRange = minPage === maxPage ? `p.${minPage}` : `p.${minPage}–${maxPage}`;

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: expanded ? 8 : 0 }}>
        <Tag minimal intent={Intent.PRIMARY} style={{ fontFamily: "var(--text-mono)", fontSize: 10 }}>
          {chunks.length} chunk{chunks.length !== 1 ? "s" : ""} · {pageRange}
        </Tag>
        {!clinicianMode && (
          <Button
            minimal small
            icon={expanded ? "chevron-up" : "chevron-down"}
            text={expanded ? "Collapse" : "Audit view"}
            onClick={() => setExpanded((v) => !v)}
            style={{ fontFamily: "var(--text-mono)", fontSize: 10 }}
          />
        )}
      </div>
      {expanded && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 4 }}>
          {chunks.map((chunk) => (
            <ChunkCard key={chunk.id} chunk={chunk} clinicianMode={clinicianMode} />
          ))}
        </div>
      )}
    </div>
  );
}

export default function IngestionPane({ clinicianMode }: { clinicianMode: boolean }) {
  const [running, setRunning]             = useState(false);
  const [steps, setSteps]                 = useState<PipelineStep[]>(INITIAL_STEPS);
  const [logLines, setLogLines]           = useState<string[]>([]);
  const [done, setDone]                   = useState(false);
  const [mdView, setMdView]               = useState<MarkdownView>("output");
  const [showDebug, setShowDebug]         = useState(false);
  const [showLog, setShowLog]             = useState(false);
  const [selectedFile, setSelectedFile]   = useState<File | null>(null);
  const [jobId, setJobId]                 = useState<string | null>(null);
  const [ocrVizUrl, setOcrVizUrl]         = useState<string | null>(null);
  const [ocrPageCount, setOcrPageCount]   = useState<number>(1);
  const [ocrPage, setOcrPage]             = useState<number>(1);
  const [liveChunks, setLiveChunks]       = useState<Chunk[]>([]);
  const [cleanedMarkdown, setCleanedMarkdown] = useState<string>("");
  const [rawOcrText, setRawOcrText]       = useState<string>("");
  const logRef                            = useRef<HTMLPreElement>(null);
  const fileRef                           = useRef<HTMLInputElement>(null);
  const readerRef                         = useRef<ReadableStreamDefaultReader<Uint8Array> | null>(null);

  useEffect(() => () => { readerRef.current?.cancel(); }, []);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [logLines]);

  // Backend step name → UI step index (4 UI slots, 5+ backend stages)
  const STEP_MAP: Record<string, number> = {
    ocr: 0, chunk: 1, convert: 2, clean: 2, vectorize: 3, kg: 3,
  };

  function setStep(i: number, patch: Partial<PipelineStep>) {
    setSteps((prev) => prev.map((s, idx) => (idx === i ? { ...s, ...patch } : s)));
  }

  function addLogLine(line: string) {
    setLogLines((prev) => [...prev, line]);
  }

  async function fetchPostRunData(slug: string, pageCount?: number) {
    // Set OCR viz image URL immediately (PNG served by ingestion API)
    setOcrVizUrl(getOcrVizUrl(slug, 1));
    setOcrPage(1);
    if (pageCount) setOcrPageCount(pageCount);

    // Parallel fetch chunks + raw markdown + cleaned markdown
    const [chunksResult, rawResult, cleanResult] = await Promise.allSettled([
      fetchChunks(slug),
      fetchMarkdownArtifact(slug),
      fetchCleanArtifact(slug),
    ]);
    if (chunksResult.status === "fulfilled") {
      setLiveChunks(chunksResult.value.sample_chunks.map(adaptChunk));
    }
    if (rawResult.status === "fulfilled") {
      setRawOcrText(rawResult.value.preview);
    }
    if (cleanResult.status === "fulfilled") {
      setCleanedMarkdown(cleanResult.value.preview);
    }
  }

  async function startIngestion() {
    if (!selectedFile) return;

    setRunning(true);
    setDone(false);
    setLogLines([]);
    setJobId(null);
    setOcrVizUrl(null);
    setOcrPage(1);
    setOcrPageCount(1);
    setLiveChunks([]);
    setCleanedMarkdown("");
    setRawOcrText("");
    setSteps(INITIAL_STEPS.map((s) => ({ ...s, progress: 0, status: "idle" as StepStatus })));

    let response: Response;
    try {
      response = await startIngestStream(selectedFile);
    } catch (err) {
      addLogLine(`[error] Failed to connect: ${String(err)}`);
      setRunning(false);
      setStep(0, { status: "failed", errorMsg: String(err) });
      return;
    }

    if (!response.ok) {
      const msg = `HTTP ${response.status} ${response.statusText}`;
      addLogLine(`[error] ${msg}`);
      setRunning(false);
      setStep(0, { status: "failed", errorMsg: msg });
      return;
    }

    const reader = response.body!.getReader();
    readerRef.current = reader;
    const decoder = new TextDecoder();
    let buffer = "";

    // Extract slug from X-Slug response header (set by the ingestion API)
    const slug = response.headers.get("X-Slug") ?? "";
    let ocrPages = 1; // captured from ocr:done SSE event

    try {
      while (true) {
        const { done: streamDone, value } = await reader.read();
        if (streamDone) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.startsWith("data:")) continue;
          const raw = line.slice(5).trim();
          if (!raw || raw === "end") continue;
          let parsed: Record<string, unknown>;
          try { parsed = JSON.parse(raw); } catch { continue; }

          const stage  = (parsed.stage  ?? "") as string;
          const status = (parsed.status ?? "") as string;
          const msg    = (parsed.message ?? "") as string;
          const extra  = (parsed.extra ?? {}) as Record<string, unknown>;

          addLogLine(`[${stage}:${status}] ${msg}`);

          // Capture slug from event if not in header
          const eventSlug = (extra.slug ?? slug) as string;

          if (stage === "done") {
            // Terminal success: mark all steps done
            setSteps(INITIAL_STEPS.map((s) => ({ ...s, status: "done", progress: 1 })));
            setRunning(false);
            setDone(true);
            if (eventSlug) {
              setJobId(eventSlug);
              fetchPostRunData(eventSlug, ocrPages);
            }
            return;
          }

          // Capture OCR page count when OCR stage completes
          if (stage === "ocr" && status === "done" && extra.pages) {
            ocrPages = extra.pages as number;
          }

          if (stage === "error") {
            const uiIdx = STEP_MAP[extra.stage as string] ?? STEP_MAP[stage] ?? 0;
            setStep(uiIdx, { status: "failed", errorMsg: msg });
            setRunning(false);
            return;
          }

          const uiIdx = STEP_MAP[stage];
          if (uiIdx !== undefined) {
            if (status === "done") {
              setStep(uiIdx, { status: "done", progress: 1 });
              // Activate next step
              const nextIdx = uiIdx + 1;
              if (nextIdx < INITIAL_STEPS.length) {
                setStep(nextIdx, { status: "active", progress: 0.1 });
              }
            } else if (status === "running") {
              setStep(uiIdx, { status: "active", progress: 0.5 });
            } else if (status === "skipped") {
              setStep(uiIdx, { status: "done", progress: 1 });
            }
          }
        }
      }
    } catch (err) {
      addLogLine(`[error] Stream read error: ${String(err)}`);
      setRunning(false);
    }
  }

  function resetPipeline() {
    readerRef.current?.cancel();
    setRunning(false);
    setDone(false);
    setLogLines([]);
    setJobId(null);
    setOcrVizUrl(null);
    setOcrPage(1);
    setOcrPageCount(1);
    setLiveChunks([]);
    setCleanedMarkdown("");
    setRawOcrText("");
    setSteps(INITIAL_STEPS);
  }

  function stepIcon(step: PipelineStep) {
    if (step.status === "done")   return <Icon icon="tick-circle" intent={Intent.SUCCESS} size={14} />;
    if (step.status === "failed") return <Icon icon="error" intent={Intent.DANGER} size={14} />;
    if (step.status === "active") return <Spinner size={14} />;
    return <Icon icon="circle" size={14} color="var(--text-dim)" />;
  }

  function stepIntent(step: PipelineStep): Intent {
    if (step.status === "done")   return Intent.SUCCESS;
    if (step.status === "failed") return Intent.DANGER;
    if (step.status === "active") return Intent.PRIMARY;
    return Intent.NONE;
  }

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>

      {/* Header */}
      <div
        style={{
          padding: "10px 16px",
          borderBottom: "1px solid var(--border)",
          display: "flex",
          alignItems: "center",
          gap: 10,
        }}
      >
        <H4 style={{ margin: 0, flex: 1, fontFamily: "var(--text-mono)", fontSize: 12, letterSpacing: "0.04em" }}>
          {clinicianMode ? "Upload Documents" : "Ingestion Pipeline"}
        </H4>
        {/* Hidden file input */}
        <input
          ref={fileRef}
          type="file"
          accept=".pdf"
          style={{ display: "none" }}
          onChange={(e) => {
            const f = e.target.files?.[0] ?? null;
            setSelectedFile(f);
            if (f) setDone(false);
          }}
        />
        {selectedFile && !running && (
          <Tag minimal icon="document" style={{ maxWidth: 180, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {selectedFile.name}
          </Tag>
        )}
        {!running && (
          <Button
            icon="folder-open"
            small
            minimal
            text={selectedFile ? "Change" : "Choose PDF"}
            onClick={() => fileRef.current?.click()}
          />
        )}
        {done && <Tag intent={Intent.SUCCESS} icon="tick-circle" minimal>{clinicianMode ? "Done" : "Complete"}</Tag>}
        {done && jobId && !clinicianMode && (
          <Tag minimal style={{ fontFamily: "var(--text-mono)", fontSize: 9 }}>job: {jobId.slice(0, 8)}</Tag>
        )}
        <Button
          icon={running ? "stop" : (clinicianMode ? "upload" : "play")}
          intent={running ? Intent.DANGER : (selectedFile ? Intent.PRIMARY : Intent.NONE)}
          small
          minimal={clinicianMode}
          disabled={!running && !selectedFile}
          text={running ? "Cancel" : done ? (clinicianMode ? "Upload again" : "Re-run") : (clinicianMode ? "Upload & Process" : "Start Ingestion")}
          onClick={running ? resetPipeline : startIngestion}
        />
      </div>

      <div
        style={{
          flex: 1,
          overflow: "auto",
          padding: "12px 16px",
          display: "flex",
          flexDirection: "column",
          gap: 16,
        }}
      >

        {/* Idle state */}
        {!running && !done && logLines.length === 0 && (
          selectedFile ? (
            <PdfPreview file={selectedFile} onStart={startIngestion} clinicianMode={clinicianMode} />
          ) : (
            <NonIdealState
              icon={clinicianMode ? "document" : "cloud-upload"}
              title={clinicianMode ? "No document selected" : "No ingestion running"}
              description={
                clinicianMode
                  ? "Choose a PDF file using the button above, then press Upload & Process."
                  : "Select a PDF using the Choose PDF button, then press Start Ingestion."
              }
              action={
                <Button icon="folder-open" onClick={() => fileRef.current?.click()}>
                  Choose PDF
                </Button>
              }
            />
          )
        )}

        {/* Pipeline steps */}
        {(running || done) && (
          clinicianMode ? (
            /* Clinician view: plain-text checkmarks, no progress bars */
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {steps.map((step) => {
                const isDone   = step.status === "done";
                const isActive = step.status === "active";
                return (
                  <div key={step.name} style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    {isDone   && <Icon icon="tick-circle" size={14} intent={Intent.SUCCESS} />}
                    {isActive && <Spinner size={14} intent={Intent.PRIMARY} />}
                    {!isDone && !isActive && <Icon icon="circle" size={14} color="var(--text-dim)" />}
                    <span style={{
                      fontSize: 13,
                      color: isDone ? "var(--text-primary)" : isActive ? "var(--text-primary)" : "var(--text-dim)",
                    }}>
                      {step.clinicianName}{isDone ? " \u2713" : ""}
                    </span>
                  </div>
                );
              })}
            </div>
          ) : (
            /* Engineer view: full progress bars */
            <Card elevation={Elevation.TWO} style={{ padding: "12px 14px" }}>
              <H5 style={{ marginBottom: 12, fontFamily: "var(--text-mono)", fontSize: 11, letterSpacing: "0.06em", textTransform: "uppercase" }}>
                Pipeline Steps
              </H5>
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {steps.map((step) => (
                  <div key={step.name}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                      {stepIcon(step)}
                      <span style={{ fontSize: 12, flex: 1 }}>{step.name}</span>
                      <span style={{ fontFamily: "var(--text-mono)", fontSize: 10, opacity: 0.55 }}>
                        {Math.round(step.progress * 100)}%
                      </span>
                    </div>
                    <ProgressBar
                      value={step.progress}
                      intent={stepIntent(step)}
                      animate={step.status === "active"}
                      stripes={step.status === "active"}
                    />
                    {step.status === "failed" && step.errorMsg && (
                      <div style={{ fontFamily: "var(--text-mono)", fontSize: 10, color: "#C97B6E", marginTop: 3 }}>
                        {step.errorMsg}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </Card>
          )
        )}

        {/* OCR Debug — engineer mode only, or clinician with showDebug */}
        {(running || done) && (!clinicianMode || showDebug) && (
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
              <H5 style={{ margin: 0, fontFamily: "var(--text-mono)", fontSize: 11, letterSpacing: "0.06em", textTransform: "uppercase" }}>
                OCR Debug Visualization
              </H5>
            </div>
            <OcrDebugViz
              vizUrl={ocrVizUrl}
              page={ocrPage}
              pageCount={ocrPageCount}
              onPageChange={(p) => {
                setOcrPage(p);
                if (jobId) setOcrVizUrl(getOcrVizUrl(jobId, p));
              }}
            />
          </div>
        )}

        {/* Clinician debug toggle */}
        {clinicianMode && (running || done) && (
          <Button
            minimal
            small
            icon={showDebug ? "eye-off" : "eye-open"}
            text={showDebug ? "Hide debug info" : "Show debug info"}
            onClick={() => setShowDebug((v) => !v)}
            style={{ alignSelf: "flex-start", fontFamily: "var(--text-mono)", fontSize: 10, color: "var(--text-dim)" }}
          />
        )}

        {/* Chunks */}
        {done && (
          <>
            <Divider />
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                <H5 style={{ margin: 0, fontFamily: "var(--text-mono)", fontSize: 11, letterSpacing: "0.06em", textTransform: "uppercase" }}>
                  {clinicianMode ? "Identified Terms" : "Extracted Chunks"}
                </H5>
                {!clinicianMode && (
                  <div style={{ display: "flex", gap: 8 }}>
                    {[
                      ["medication", "#c49a3c"],
                      ["condition", "#C97B6E"],
                      ["measurement", "#A3B899"],
                      ["protocol", "#6a9bc0"],
                    ].map(([type, color]) => (
                      <span key={type} style={{ fontFamily: "var(--text-mono)", fontSize: 9, color }}>■ {type}</span>
                    ))}
                  </div>
                )}
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {liveChunks.length > 0
                  ? <ChunkSummary chunks={liveChunks} clinicianMode={clinicianMode} />
                  : (
                    <NonIdealState
                      icon="layers"
                      title="No chunks yet"
                      description="Chunks will appear here after ingestion completes."
                    />
                  )
                }
              </div>
            </div>

            {!clinicianMode && (
              <>
                <Divider />

                {/* Cleaned markdown */}
                <div>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                    <H5 style={{ margin: 0, fontFamily: "var(--text-mono)", fontSize: 11, letterSpacing: "0.06em", textTransform: "uppercase" }}>
                      Cleaned Markdown
                    </H5>
                    <div style={{ display: "flex", gap: 1 }}>
                      {(["output", "diff"] as MarkdownView[]).map((v) => (
                        <Button
                          key={v}
                          small
                          minimal={mdView !== v}
                          active={mdView === v}
                          intent={mdView === v ? Intent.PRIMARY : Intent.NONE}
                          text={v.toUpperCase()}
                          onClick={() => setMdView(v)}
                          style={{ fontFamily: "var(--text-mono)", fontSize: 9, letterSpacing: "0.06em" }}
                        />
                      ))}
                    </div>
                  </div>

                  {mdView === "output" ? (
                    <Card elevation={Elevation.ONE} style={{ padding: "10px 14px" }}>
                      {cleanedMarkdown ? (
                        <Pre style={{ margin: 0, fontSize: 11.5, lineHeight: 1.75, whiteSpace: "pre-wrap" }}>
                          {cleanedMarkdown}
                        </Pre>
                      ) : (
                        <span style={{ fontFamily: "var(--text-mono)", fontSize: 10, color: "var(--text-dim)" }}>
                          Markdown output available after ingestion completes.
                        </span>
                      )}
                    </Card>
                  ) : (
                    <MarkdownDiff rawOcrText={rawOcrText} cleanedMarkdown={cleanedMarkdown} />
                  )}
                </div>
              </>
            )}
          </>
        )}

        {/* SSE Event Log */}
        {logLines.length > 0 && (
          <div>
            <Divider />
            {clinicianMode ? (
              <Button
                minimal
                small
                icon={showLog ? "chevron-up" : "chevron-down"}
                text={showLog ? "Hide processing log" : "Show processing log"}
                onClick={() => setShowLog((v) => !v)}
                style={{ fontFamily: "var(--text-mono)", fontSize: 10, color: "var(--text-dim)", marginBottom: showLog ? 6 : 0 }}
              />
            ) : (
              <H5 style={{ margin: "8px 0", fontFamily: "var(--text-mono)", fontSize: 11, letterSpacing: "0.06em", textTransform: "uppercase" }}>
                Event Log (SSE)
              </H5>
            )}
            {(!clinicianMode || showLog) && (
              <Pre
                ref={logRef}
                style={{
                  height: 130,
                  overflowY: "auto",
                  fontSize: 10.5,
                  lineHeight: 1.7,
                  whiteSpace: "pre-wrap",
                  margin: 0,
                }}
              >
                {logLines.join("\n")}
                {running && <span className={Classes.SKELETON} style={{ display: "inline-block", width: 120 }} />}
              </Pre>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
