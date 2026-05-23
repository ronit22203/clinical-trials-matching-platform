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
import { startIngestStream, fetchOCRDebug, fetchChunks, fetchMarkdown } from "../lib/api";
import { adaptOcrBoxes, adaptOcrHeatmap, adaptChunk } from "../lib/adapters";
import type { OcrBox, UIChunk } from "../lib/adapters";

// ─── Types ────────────────────────────────────────────────────

type StepStatus = "idle" | "active" | "done" | "failed";
type OcrMode = "boxes" | "heatmap";
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

// ─── Helpers ──────────────────────────────────────────────────

function confToColor(conf: string | number): string {
  const v = typeof conf === "number" ? conf : conf === "high" ? 0.95 : conf === "medium" ? 0.72 : 0.42;
  if (v >= 0.85) return "#2aa198";
  if (v >= 0.65) return "#b58900";
  return "#cb4b16";
}

function heatmapCellColor(v: number): string {
  // cyan (high) → amber (mid) → orange (low)
  if (v >= 0.85) return `rgba(42, 161, 152, ${0.12 + (v - 0.85) * 0.6})`;
  if (v >= 0.65) return `rgba(181, 137, 0,  ${0.12 + (0.85 - v) * 0.5})`;
  return `rgba(203, 75, 22, ${0.15 + (0.65 - v) * 0.6})`;
}

// ─── Sub-components ───────────────────────────────────────────

function OcrDebugViz({
  mode,
  boxes,
  heatmap,
}: {
  mode: OcrMode;
  boxes: OcrBox[];
  heatmap: number[][];
}) {
  if (boxes.length === 0 && mode === "boxes") {
    return (
      <Card elevation={Elevation.ONE} style={{ height: 175, display: "flex", alignItems: "center", justifyContent: "center", background: "var(--surface-2)", borderRadius: 6 }}>
        <span style={{ fontFamily: "var(--text-mono)", fontSize: 10, color: "var(--text-dim)" }}>OCR data available after ingestion completes</span>
      </Card>
    );
  }
  if (heatmap.length === 0 && mode === "heatmap") {
    return (
      <Card elevation={Elevation.ONE} style={{ height: 175, display: "flex", alignItems: "center", justifyContent: "center", background: "var(--surface-2)", borderRadius: 6 }}>
        <span style={{ fontFamily: "var(--text-mono)", fontSize: 10, color: "var(--text-dim)" }}>Heatmap available after ingestion completes</span>
      </Card>
    );
  }
  return (
    <Card
      elevation={Elevation.ONE}
      style={{ position: "relative", height: 175, overflow: "hidden", background: "var(--surface-2)", borderRadius: 6 }}
    >
      {/* Page line grid */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          background: "repeating-linear-gradient(0deg, transparent, transparent 19px, rgba(255,255,255,0.03) 20px)",
          pointerEvents: "none",
        }}
      />

      {mode === "boxes" && (
        <>
          {boxes.map((box, i) => {
            const color = confToColor(box.conf);
            return (
              <div
                key={i}
                style={{
                  position: "absolute",
                  top: box.top, left: box.left,
                  width: box.width, height: box.height,
                  border: `1px solid ${color}`,
                  borderRadius: 1,
                  display: "flex",
                  alignItems: "center",
                  paddingLeft: 3,
                  background: `${color}0d`,
                }}
              >
                <span style={{ fontSize: 8.5, color, whiteSpace: "nowrap", fontFamily: "monospace" }}>
                  {box.label}
                </span>
              </div>
            );
          })}
          <div style={{ position: "absolute", bottom: 5, right: 6, display: "flex", gap: 5 }}>
            {[["#2aa198", "high"], ["#b58900", "mid"], ["#cb4b16", "low"]].map(([col, label]) => (
              <span key={label} style={{ fontFamily: "monospace", fontSize: 9, color: col }}>
                ■ {label}
              </span>
            ))}
          </div>
        </>
      )}

      {mode === "heatmap" && (
        <>
          {heatmap.map((row, ri) =>
            row.map((val, ci) => (
              <div
                key={`${ri}-${ci}`}
                style={{
                  position: "absolute",
                  top:  4 + ri * 18.5,
                  left: 4 + ci * 74,
                  width: 70,
                  height: 16,
                  background: heatmapCellColor(val),
                  borderRadius: 1,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                <span style={{ fontFamily: "monospace", fontSize: 8, color: "rgba(255,255,255,0.55)" }}>
                  {val.toFixed(2)}
                </span>
              </div>
            ))
          )}
          <div style={{ position: "absolute", bottom: 5, right: 6, display: "flex", gap: 5 }}>
            {[["rgba(61,220,151,0.5)", "≥0.85"], ["rgba(196,154,60,0.5)", "0.65–0.84"], ["rgba(255,107,107,0.5)", "<0.65"]].map(([col, label]) => (
              <span key={label} style={{ fontFamily: "monospace", fontSize: 9, color: "var(--text-dim)" }}>
                <span style={{ background: col, padding: "0 3px", borderRadius: 1 }}>{label}</span>
              </span>
            ))}
          </div>
        </>
      )}
    </Card>
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

export default function IngestionPane({ clinicianMode }: { clinicianMode: boolean }) {
  const [running, setRunning]             = useState(false);
  const [steps, setSteps]                 = useState<PipelineStep[]>(INITIAL_STEPS);
  const [logLines, setLogLines]           = useState<string[]>([]);
  const [done, setDone]                   = useState(false);
  const [ocrMode, setOcrMode]             = useState<OcrMode>("boxes");
  const [mdView, setMdView]               = useState<MarkdownView>("output");
  const [showDebug, setShowDebug]         = useState(false);
  const [showLog, setShowLog]             = useState(false);
  const [selectedFile, setSelectedFile]   = useState<File | null>(null);
  const [jobId, setJobId]                 = useState<string | null>(null);
  const [ocrBoxes, setOcrBoxes]           = useState<OcrBox[]>([]);
  const [heatmapGrid, setHeatmapGrid]     = useState<number[][]>([]);
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

  // Backend step name → UI step index (4 UI slots, 5 backend stages)
  const STEP_MAP: Record<string, number> = {
    ocr: 0, chunk: 1, convert: 2, clean: 2, vectorize: 3,
  };

  function setStep(i: number, patch: Partial<PipelineStep>) {
    setSteps((prev) => prev.map((s, idx) => (idx === i ? { ...s, ...patch } : s)));
  }

  function addLogLine(line: string) {
    setLogLines((prev) => [...prev, line]);
  }

  async function fetchPostRunData(id: string) {
    // Parallel fetch OCR debug + chunks + markdown after pipeline completes
    const [ocrResult, chunksResult, markdownResult] = await Promise.allSettled([
      fetchOCRDebug(id),
      fetchChunks(id),
      fetchMarkdown(id),
    ]);
    if (ocrResult.status === "fulfilled" && ocrResult.value.pages.length > 0) {
      setOcrBoxes(adaptOcrBoxes(ocrResult.value.pages[0]));
      setHeatmapGrid(adaptOcrHeatmap(ocrResult.value.pages[0]));
    }
    if (chunksResult.status === "fulfilled") {
      setLiveChunks(chunksResult.value.chunks.map(adaptChunk));
    }
    if (markdownResult.status === "fulfilled") {
      setCleanedMarkdown(markdownResult.value.markdown);
      setRawOcrText(markdownResult.value.cleaning_log.join("\n"));
    }
  }

  async function startIngestion() {
    if (!selectedFile) return;

    setRunning(true);
    setDone(false);
    setLogLines([]);
    setJobId(null);
    setOcrBoxes([]);
    setHeatmapGrid([]);
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
    let currentEvent = "";

    try {
      while (true) {
        const { done: streamDone, value } = await reader.read();
        if (streamDone) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (line.startsWith("event:")) {
            currentEvent = line.slice(6).trim();
          } else if (line.startsWith("data:")) {
            const raw = line.slice(5).trim();
            if (!raw) continue;
            let parsed: Record<string, unknown>;
            try { parsed = JSON.parse(raw); } catch { continue; }

            addLogLine(`[${currentEvent}] ${JSON.stringify(parsed)}`);

            if (currentEvent === "progress") {
              const stepName = (parsed.step ?? "") as string;
              const uiIdx = STEP_MAP[stepName] ?? -1;
              if (uiIdx >= 0) {
                const progress = typeof parsed.progress === "number" ? parsed.progress : 0;
                const prevStatus = steps[uiIdx]?.status;
                const newStatus: StepStatus = progress >= 1 ? "done" : "active";
                // Activate the next step if this one just completed
                if (newStatus === "done" && prevStatus !== "done") {
                  setStep(uiIdx, { status: "done", progress: 1 });
                  const nextIdx = uiIdx + 1;
                  if (nextIdx < INITIAL_STEPS.length) {
                    setStep(nextIdx, { status: "active", progress: 0.1 });
                  }
                } else {
                  setStep(uiIdx, { status: newStatus, progress });
                }
              }
            } else if (currentEvent === "error") {
              const msg = (parsed.message ?? "Unknown error") as string;
              const stepName = (parsed.step ?? "") as string;
              const uiIdx = STEP_MAP[stepName] ?? 0;
              setStep(uiIdx, { status: "failed", errorMsg: msg });
              setRunning(false);
              return;
            } else if (currentEvent === "complete") {
              const id = (parsed.job_id ?? parsed.jobId ?? "") as string;
              setSteps(INITIAL_STEPS.map((s) => ({ ...s, status: "done", progress: 1 })));
              setRunning(false);
              setDone(true);
              setJobId(id);
              if (id) fetchPostRunData(id);
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
    setOcrBoxes([]);
    setHeatmapGrid([]);
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
            <NonIdealState
              icon="document"
              title={selectedFile.name}
              description={
                clinicianMode
                  ? "Document ready. Press Upload & Process to begin."
                  : `PDF selected (${(selectedFile.size / 1024).toFixed(0)} KB). Press Start Ingestion to begin.`
              }
              action={
                <Button intent={Intent.PRIMARY} icon={clinicianMode ? "upload" : "play"} onClick={startIngestion}>
                  {clinicianMode ? "Upload & Process" : "Start Ingestion"}
                </Button>
              }
            />
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
              <div style={{ display: "flex", gap: 1 }}>
                {(["boxes", "heatmap"] as OcrMode[]).map((m) => (
                  <Button
                    key={m}
                    small
                    minimal={ocrMode !== m}
                    active={ocrMode === m}
                    intent={ocrMode === m ? Intent.PRIMARY : Intent.NONE}
                    text={m.toUpperCase()}
                    onClick={() => setOcrMode(m)}
                    style={{ fontFamily: "var(--text-mono)", fontSize: 9, letterSpacing: "0.06em" }}
                  />
                ))}
              </div>
            </div>
            <OcrDebugViz mode={ocrMode} boxes={ocrBoxes} heatmap={heatmapGrid} />
            {ocrMode === "boxes" && ocrBoxes.length > 0 && (
              <div style={{ marginTop: 6, fontFamily: "var(--text-mono)", fontSize: 10, color: "var(--text-dim)" }}>
                {ocrBoxes.filter((b) => b.conf === "low").length} low-confidence words flagged ·{" "}
                {ocrBoxes.filter((b) => b.conf === "medium").length} medium
              </div>
            )}
            {ocrMode === "heatmap" && (
              <div style={{ marginTop: 6, fontFamily: "var(--text-mono)", fontSize: 10, color: "var(--text-dim)" }}>
                grid: 6 × 9 confidence cells · page 4 of 5
              </div>
            )}
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
                  ? liveChunks.map((chunk) => (
                      <ChunkCard key={chunk.id} chunk={chunk} clinicianMode={clinicianMode} />
                    ))
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
