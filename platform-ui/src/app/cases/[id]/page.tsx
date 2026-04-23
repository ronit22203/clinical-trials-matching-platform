"use client";

import { useState } from "react";
import AppShell from "@/components/layout/AppShell";
import RightPanel from "@/components/layout/RightPanel";
import CaseArtifacts from "@/components/case/CaseArtifacts";
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
      relevanceScore: TOOL_SOURCE[tool] === "graphrag" ? 0.92 : 0.78,
    }));
}

export default function CaseDetailPage() {
  const [selectedTrial, setSelectedTrial] = useState<Trial | null>(null);
  const [executionLog, setExecutionLog] = useState<ExecutionLog | null>(null);
  const [citations, setCitations] = useState<Citation[]>([]);

  function handleQueryComplete(result: QueryResponse) {
    setExecutionLog(result.executionLog);
    setCitations(toolResultsToCitations(result.toolResults ?? {}));
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
        <CaseArtifacts executionLog={executionLog} citationCount={citations.length} />
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
