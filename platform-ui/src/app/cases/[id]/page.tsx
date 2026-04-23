"use client";

import { useState, useEffect, useCallback } from "react";
import AppShell from "@/components/layout/AppShell";
import RightPanel from "@/components/layout/RightPanel";
import CaseArtifacts, { type ArtifactAction } from "@/components/case/CaseArtifacts";
import QuickActions from "@/components/case/QuickActions";
import AIQueryPanel from "@/components/case/AIQueryPanel";
import TrialDrillDown from "@/components/match/TrialDrillDown";
import type { Trial } from "@/lib/types/trial";
import type { Citation, EvidenceSource } from "@/lib/types/evidence";
import type { ExecutionLog } from "@/lib/types/audit";
import type { QueryResponse } from "@/lib/api/client";

const TOOL_TITLES: Record<string, string> = {
  pubmed: "PubMed Literature Search",
  clinicaltrials: "ClinicalTrials.gov Results",
  graphrag: "Knowledge Graph Retrieval",
  graphrag_search: "Knowledge Graph Retrieval",
  mcp_filesystem: "Local Filesystem Search",
};

const TOOL_SOURCE: Record<string, EvidenceSource> = {
  pubmed: "pubmed",
  clinicaltrials: "clinicaltrials",
  graphrag: "graphrag",
  graphrag_search: "graphrag",
};

function toolResultsToCitations(toolResults: Record<string, string>): Citation[] {
  return Object.entries(toolResults)
    .filter(([, text]) => text && text.trim().length > 20)
    .map(([tool, text], idx) => ({
      id: `${tool}-${idx}`,
      title: TOOL_TITLES[tool] ?? tool,
      authors: "Retrieved via AI agent",
      year: new Date().getFullYear(),
      source: (TOOL_SOURCE[tool] ?? "graphrag") as EvidenceSource,
      snippet: text.trim().slice(0, 450) + (text.length > 450 ? "…" : ""),
      url: "#",
      relevanceScore: (TOOL_SOURCE[tool] ?? "graphrag") === "graphrag" ? 0.92 : 0.78,
    }));
}

const SESSION_KEY = "mara-active-case";

interface PersistedSession {
  executionLog: ExecutionLog;
  citations: Citation[];
  documentName: string | null;
  entityCount: number | null;
}

export default function CaseDetailPage() {
  const [selectedTrial, setSelectedTrial] = useState<Trial | null>(null);
  const [executionLog, setExecutionLog] = useState<ExecutionLog | null>(null);
  const [citations, setCitations] = useState<Citation[]>([]);
  const [documentName, setDocumentName] = useState<string | null>(null);
  const [entityCount, setEntityCount] = useState<number | null>(null);

  // Restore session on mount
  useEffect(() => {
    try {
      const saved = sessionStorage.getItem(SESSION_KEY);
      if (saved) {
        const s: PersistedSession = JSON.parse(saved);
        if (s.executionLog) setExecutionLog(s.executionLog);
        if (s.citations?.length) setCitations(s.citations);
        if (s.documentName) setDocumentName(s.documentName);
        if (s.entityCount != null) setEntityCount(s.entityCount);
      }
    } catch { /* corrupt storage — ignore */ }
  }, []);

  const persistSession = useCallback((s: PersistedSession) => {
    try { sessionStorage.setItem(SESSION_KEY, JSON.stringify(s)); } catch { /* quota exceeded — ignore */ }
  }, []);

  function handleQueryComplete(result: QueryResponse) {
    const newCitations = toolResultsToCitations(result.toolResults ?? {});

    // Extract document ID from GraphRAG result text (e.g. "2026.03.17.26348414")
    const graphragText = result.toolResults?.graphrag ?? result.toolResults?.graphrag_search ?? "";
    const docMatch = graphragText.match(/\d{4}\.\d{2}\.\d{2}\.\d+/);
    const newDocName = docMatch ? `${docMatch[0]}_cleaned.md` : null;

    // Count bold-marked terms as a proxy for structured entities
    const boldMatches = result.synthesis.match(/\*\*[^*]+\*\*/g);
    const newEntityCount = boldMatches ? boldMatches.length : null;

    setExecutionLog(result.executionLog);
    setCitations(newCitations);
    setDocumentName(newDocName);
    setEntityCount(newEntityCount);

    persistSession({
      executionLog: result.executionLog,
      citations: newCitations,
      documentName: newDocName,
      entityCount: newEntityCount,
    });
  }

  function handleArtifactAction(action: ArtifactAction) {
    switch (action) {
      case "inspect-profile":
        // Open Neo4j browser — most useful action available locally
        window.open("http://localhost:7474", "_blank");
        break;
      case "inspect-logs":
        if (!executionLog) return;
        // Trigger a JSON download of the full execution log
        const blob = new Blob([JSON.stringify(executionLog, null, 2)], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `execution-${executionLog.executionId.slice(0, 8)}.json`;
        a.click();
        URL.revokeObjectURL(url);
        break;
      default:
        break;
    }
  }

  const rightPanel = (
    <RightPanel
      trials={[]}
      citations={citations}
      executionLog={executionLog}
      onSelectTrial={setSelectedTrial}
    />
  );

  return (
    <>
      <AppShell activePath="/cases" rightPanel={rightPanel}>
        <div className="px-6 pt-6 pb-4 bg-surface">
          <p
            className="text-[11px] uppercase tracking-[0.08em] text-on-surface-variant mb-1"
            style={{ fontFamily: "var(--font-manrope)" }}
          >
            Patient Case
          </p>
          <h1
            className="text-2xl font-bold text-on-surface"
            style={{ fontFamily: "var(--font-manrope)" }}
          >
            {executionLog ? "Active Session" : "No case loaded"}
          </h1>
          <p className="mt-1 text-sm text-on-surface-variant">
            {executionLog
              ? `Run ${executionLog.executionId.slice(0, 8)} · ${executionLog.toolsCalled.length} tool${executionLog.toolsCalled.length !== 1 ? "s" : ""} called`
              : "Connect the API to load real patient data."}
          </p>
          <div className="mt-4 h-px bg-surface-highest opacity-70" />
        </div>
        <CaseArtifacts
          executionLog={executionLog}
          citationCount={citations.length}
          documentName={documentName}
          entityCount={entityCount}
          trialCount={0}
          onAction={handleArtifactAction}
        />
        <QuickActions />
        <AIQueryPanel onQueryComplete={handleQueryComplete} />
      </AppShell>

      {selectedTrial && (
        <TrialDrillDown
          trial={selectedTrial}
          patient={null as never}
          onClose={() => setSelectedTrial(null)}
        />
      )}
    </>
  );
}
