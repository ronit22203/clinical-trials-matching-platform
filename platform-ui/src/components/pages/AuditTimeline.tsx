"use client";

import { useState } from "react";
import type { ExecutionLog, AuditEntry, AuditStepType } from "@/lib/types/audit";
import { cn, formatTimestamp } from "@/lib/utils";
import { ChevronDown, ChevronRight } from "lucide-react";

const STEP_CONFIG: Record<AuditStepType, { label: string; color: string; dot: string }> = {
  query_submitted: {
    label: "Query Submitted",
    color: "text-primary",
    dot: "bg-primary",
  },
  tool_called: {
    label: "Tool Called",
    color: "text-tertiary",
    dot: "bg-tertiary",
  },
  data_retrieved: {
    label: "Data Retrieved",
    color: "text-on-surface-variant",
    dot: "bg-primary-fixed-dim",
  },
  hitl_pending: {
    label: "HITL Pending",
    color: "text-status-partial",
    dot: "bg-status-partial",
  },
  final_decision: {
    label: "Final Decision",
    color: "text-status-eligible",
    dot: "bg-status-eligible",
  },
};

function AuditNode({ entry, isLast }: { entry: AuditEntry; isLast: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const config = STEP_CONFIG[entry.step];

  return (
    <div className="flex gap-3">
      {/* Timeline line */}
      <div className="flex flex-col items-center">
        <div className={cn("w-3 h-3 rounded-full shrink-0 mt-0.5", config.dot)} />
        {!isLast && <div className="w-px flex-1 bg-surface-highest mt-1" />}
      </div>

      {/* Content */}
      <div className={cn("pb-6 flex-1 min-w-0", isLast && "pb-0")}>
        <button
          onClick={() => setExpanded((v) => !v)}
          className="w-full text-left group"
        >
          <div className="flex items-start justify-between gap-2">
            <div>
              <p className={cn("text-sm font-semibold", config.color)}>
                {entry.label}
              </p>
              <p className="text-xs text-on-surface-variant mt-0.5">
                {formatTimestamp(entry.timestamp)}
                {entry.durationMs && (
                  <span className="ml-2 font-mono">+{entry.durationMs}ms</span>
                )}
                {entry.toolName && (
                  <span className="ml-2 px-1.5 py-0.5 rounded-md bg-surface-container text-on-surface-variant uppercase tracking-wide text-[9px]">
                    {entry.toolName}
                  </span>
                )}
              </p>
            </div>
            <span className="text-on-surface-variant mt-0.5 shrink-0">
              {expanded ? (
                <ChevronDown className="w-3.5 h-3.5" />
              ) : (
                <ChevronRight className="w-3.5 h-3.5" />
              )}
            </span>
          </div>
        </button>

        {expanded && (
          <div className="mt-3 rounded-xl bg-surface-container p-3 overflow-x-auto">
            <pre className="text-[11px] font-mono text-on-surface-variant leading-relaxed whitespace-pre-wrap">
              {JSON.stringify(entry.rawJson, null, 2)}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}

interface AuditTimelineProps {
  log: ExecutionLog;
}

export default function AuditTimeline({ log }: AuditTimelineProps) {
  const isEmpty = !log.executionId && log.entries.length === 0;

  return (
    <div className="p-6 space-y-6 max-w-3xl">
      <div>
        <h1
          className="text-xl font-bold text-on-surface mb-1"
          style={{ fontFamily: "var(--font-manrope)" }}
        >
          Audit Trail
        </h1>
        {!isEmpty && (
          <div className="flex items-center gap-3 mt-2">
            <span className="text-xs font-mono text-on-surface-variant bg-surface-container px-2 py-1 rounded-lg">
              {log.executionId}
            </span>
            <span className="text-xs text-on-surface-variant">
              {log.model} · {(log.latencyMs / 1000).toFixed(2)}s · {log.routerIntent}
            </span>
          </div>
        )}
      </div>

      {isEmpty ? (
        <div className="rounded-2xl bg-surface-lowest ambient-shadow p-12 flex flex-col items-center text-center">
          <p className="text-sm font-medium text-on-surface-variant">No execution recorded yet</p>
          <p className="text-xs text-on-surface-variant mt-1">
            Run a query in the case view to populate the audit trail.
          </p>
        </div>
      ) : (
        <div className="rounded-2xl bg-surface-lowest ambient-shadow p-6">
          {log.entries.map((entry, i) => (
            <AuditNode key={entry.id} entry={entry} isLast={i === log.entries.length - 1} />
          ))}
        </div>
      )}
    </div>
  );
}
