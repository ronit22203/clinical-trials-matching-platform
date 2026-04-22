"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import type { Trial } from "@/lib/types/trial";
import type { Citation } from "@/lib/types/evidence";
import type { ExecutionLog } from "@/lib/types/audit";
import RankedTrials from "@/components/match/RankedTrials";
import EvidencePanel from "@/components/match/EvidencePanel";
import ReasoningTrace from "@/components/match/ReasoningTrace";

const TABS = ["Trials", "Evidence", "Reasoning"] as const;
type TabId = (typeof TABS)[number];

interface RightPanelProps {
  trials: Trial[];
  citations: Citation[];
  executionLog: ExecutionLog | null;
  onSelectTrial?: (trial: Trial) => void;
}

export default function RightPanel({
  trials,
  citations,
  executionLog,
  onSelectTrial,
}: RightPanelProps) {
  const [activeTab, setActiveTab] = useState<TabId>("Trials");

  return (
    <div className="flex flex-col h-full">
      {/* Tab strip */}
      <div className="flex items-center px-4 pt-4 pb-0 gap-1 shrink-0">
        {TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={cn(
              "px-3 py-1.5 rounded-lg text-xs font-medium transition-colors",
              activeTab === tab
                ? "bg-surface-container text-primary"
                : "text-on-surface-variant hover:bg-surface-container hover:text-on-surface"
            )}
          >
            {tab}
          </button>
        ))}

        {/* Match count badge */}
        {activeTab === "Trials" && (
          <span className="ml-auto text-[10px] uppercase tracking-widest text-on-surface-variant">
            {trials.length} matched
          </span>
        )}
      </div>

      {/* Divider (background shift — no line) */}
      <div className="mx-4 mt-3 mb-0 h-px bg-surface-highest opacity-60" />

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {activeTab === "Trials" && (
          <RankedTrials trials={trials} onSelect={onSelectTrial} />
        )}
        {activeTab === "Evidence" && <EvidencePanel citations={citations} />}
        {activeTab === "Reasoning" && (
          <ReasoningTrace executionLog={executionLog} />
        )}
      </div>
    </div>
  );
}
