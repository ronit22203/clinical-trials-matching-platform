"use client";

import { useState } from "react";
import type { ExecutionLog } from "@/lib/types/audit";
import { cn } from "@/lib/utils";
import { ChevronDown, ChevronRight } from "lucide-react";

interface ReasoningTraceProps {
  executionLog: ExecutionLog | null;
}

export default function ReasoningTrace({ executionLog }: ReasoningTraceProps) {
  if (!executionLog) {
    return (
      <p className="text-sm text-on-surface-variant text-center py-8">
        No execution log available. Run matching first.
      </p>
    );
  }

  const toolsCalled = executionLog.toolsCalled;
  const entities = ["EGFR_Exon19Del", "Osimertinib", "Adenocarcinoma_NSCLC", "NSCLC_StageIIIB"];
  const retrievalPath = [
    { step: "Query encoding", detail: "qwen3:1.7b → 312 tokens" },
    { step: "Vector search (Qdrant)", detail: "5 hits · BGE-small-en-v1.5" },
    { step: "Graph traversal (Neo4j)", detail: "depth 2 · 347 edges" },
    { step: "Re-ranking", detail: "cross-encoder · top 5 returned" },
  ];

  return (
    <div className="space-y-4">
      {/* Execution meta */}
      <div className="rounded-2xl bg-surface-lowest p-3 space-y-1">
        <p className="text-[10px] uppercase tracking-widest text-on-surface-variant mb-2">
          Execution
        </p>
        <MetaRow label="ID" value={executionLog.executionId.slice(0, 16) + "…"} />
        <MetaRow label="Model" value={executionLog.model} />
        <MetaRow label="Latency" value={`${(executionLog.latencyMs / 1000).toFixed(2)}s`} />
        <MetaRow
          label="Tokens"
          value={`${executionLog.tokensInput} in · ${executionLog.tokensOutput} out`}
        />
        <MetaRow label="Runtime" value={executionLog.routerIntent} />
      </div>

      {/* Tools used */}
      <div>
        <p className="text-[10px] uppercase tracking-widest text-on-surface-variant mb-2">
          Tools Used
        </p>
        <div className="flex flex-wrap gap-1.5">
          {toolsCalled.map((t) => (
            <span
              key={t}
              className="px-2 py-1 rounded-lg bg-[rgba(0,80,80,0.08)] text-primary text-xs font-medium"
            >
              {t}
            </span>
          ))}
        </div>
      </div>

      {/* Retrieval path */}
      <div>
        <p className="text-[10px] uppercase tracking-widest text-on-surface-variant mb-2">
          Retrieval Path
        </p>
        <div className="space-y-1">
          {retrievalPath.map(({ step, detail }, i) => (
            <div key={i} className="flex items-start gap-2">
              <div className="mt-1.5 w-1.5 h-1.5 rounded-full bg-primary-fixed-dim shrink-0" />
              <div>
                <span className="text-xs font-medium text-on-surface">{step}</span>
                <span className="text-xs text-on-surface-variant ml-1.5">{detail}</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Key entities */}
      <div>
        <p className="text-[10px] uppercase tracking-widest text-on-surface-variant mb-2">
          Key Entities Matched
        </p>
        <div className="flex flex-wrap gap-1.5">
          {entities.map((e) => (
            <span key={e} className="entity-highlight text-xs px-1.5 py-0.5 font-medium">
              {e}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

function MetaRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-[10px] uppercase tracking-widest text-on-surface-variant">{label}</span>
      <span className="text-xs font-mono text-on-surface">{value}</span>
    </div>
  );
}
