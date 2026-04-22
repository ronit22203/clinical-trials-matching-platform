"use client";

import { useState } from "react";
import AppShell from "@/components/layout/AppShell";
import RightPanel from "@/components/layout/RightPanel";
import CaseHeader from "@/components/case/CaseHeader";
import CaseArtifacts from "@/components/case/CaseArtifacts";
import QuickActions from "@/components/case/QuickActions";
import AIQueryPanel from "@/components/case/AIQueryPanel";
import TrialDrillDown from "@/components/match/TrialDrillDown";
import type { Trial } from "@/lib/types/trial";
import type { ExecutionLog } from "@/lib/types/audit";
import type { QueryResponse } from "@/lib/api/client";

export default function CaseDetailPage() {
  const [selectedTrial, setSelectedTrial] = useState<Trial | null>(null);
  const [executionLog, setExecutionLog] = useState<ExecutionLog | null>(null);

  function handleQueryComplete(result: QueryResponse) {
    setExecutionLog(result.executionLog);
  }

  const rightPanel = (
    <RightPanel
      trials={[]}
      citations={[]}
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
            No case loaded
          </h1>
          <p className="mt-1 text-sm text-on-surface-variant">
            Connect the API to load real patient data.
          </p>
          <div className="mt-4 h-px bg-surface-highest opacity-70" />
        </div>
        <CaseArtifacts />
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
