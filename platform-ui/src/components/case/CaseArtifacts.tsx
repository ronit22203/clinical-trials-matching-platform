"use client";

import { FileText, Code2, ListOrdered, BookMarked, Terminal, ArrowRight } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ExecutionLog } from "@/lib/types/audit";

export type ArtifactAction =
  | "view-record"
  | "inspect-profile"
  | "view-matches"
  | "browse-evidence"
  | "inspect-logs";

interface CaseArtifactsProps {
  executionLog?: ExecutionLog | null;
  citationCount?: number;
  documentName?: string | null;
  entityCount?: number | null;
  trialCount?: number;
  onAction?: (action: ArtifactAction) => void;
}

export default function CaseArtifacts({
  executionLog,
  citationCount = 0,
  documentName,
  entityCount,
  trialCount = 0,
  onAction,
}: CaseArtifactsProps) {
  const ARTIFACTS = [
    {
      id: "record",
      title: "Patient Record",
      subtitle: documentName ?? "No document loaded — run a query first",
      icon: FileText,
      tag: "PDF",
      tagClass: documentName
        ? "bg-[rgba(0,80,80,0.08)] text-primary"
        : "bg-surface-highest text-on-surface-variant",
      action: "View",
      actionId: "view-record" as ArtifactAction,
    },
    {
      id: "profile",
      title: "Clinical Profile",
      subtitle: entityCount != null
        ? `Extracted JSON — ${entityCount} entities`
        : "Run a query to extract entities",
      icon: Code2,
      tag: "JSON",
      tagClass: entityCount != null
        ? "bg-[rgba(0,73,125,0.08)] text-tertiary"
        : "bg-surface-highest text-on-surface-variant",
      action: "Inspect",
      actionId: "inspect-profile" as ArtifactAction,
    },
    {
      id: "matches",
      title: "Trial Matches",
      subtitle: trialCount > 0
        ? `${trialCount} trial${trialCount !== 1 ? "s" : ""} ranked by eligibility score`
        : "No trials matched yet",
      icon: ListOrdered,
      tag: "Ranked",
      tagClass: trialCount > 0
        ? "bg-[rgba(22,163,74,0.08)] text-status-eligible"
        : "bg-surface-highest text-on-surface-variant",
      action: "View",
      actionId: "view-matches" as ArtifactAction,
    },
    {
      id: "evidence",
      title: "Evidence Pack",
      subtitle: executionLog && citationCount > 0
        ? `${citationCount} citation${citationCount !== 1 ? "s" : ""} · ${executionLog.toolsCalled.length} source${executionLog.toolsCalled.length !== 1 ? "s" : ""}`
        : "No evidence yet",
      icon: BookMarked,
      tag: "Citations",
      tagClass: citationCount > 0
        ? "bg-[rgba(132,212,211,0.2)] text-primary"
        : "bg-surface-highest text-on-surface-variant",
      action: "Browse",
      actionId: "browse-evidence" as ArtifactAction,
    },
    {
      id: "logs",
      title: "Execution Logs",
      subtitle: executionLog
        ? `Run ${executionLog.executionId.slice(0, 7)} · ${(executionLog.latencyMs / 1000).toFixed(1)}s · ${executionLog.toolsCalled.length} tools`
        : "No runs yet",
      icon: Terminal,
      tag: "JSONL",
      tagClass: executionLog
        ? "bg-[rgba(0,80,80,0.08)] text-primary"
        : "bg-surface-highest text-on-surface-variant",
      action: "Download",
      actionId: "inspect-logs" as ArtifactAction,
    },
  ] as const;

  return (
    <section className="px-6 py-4">
      <h2
        className="text-[11px] uppercase tracking-[0.08em] text-on-surface-variant mb-3"
        style={{ fontFamily: "var(--font-manrope)" }}
      >
        Case Artifacts
      </h2>

      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-5">
        {ARTIFACTS.map(({ id, title, subtitle, icon: Icon, tag, tagClass, action, actionId }) => (
          <div
            key={id}
            onClick={() => onAction?.(actionId)}
            className={cn(
              "group relative flex flex-col gap-2 p-4 rounded-2xl bg-surface-lowest ambient-shadow cursor-pointer",
              "hover:shadow-[0_8px_24px_rgba(0,80,80,0.09)] transition-shadow"
            )}
          >
            <div className="flex items-start justify-between">
              <div className="w-9 h-9 rounded-xl bg-surface-container flex items-center justify-center">
                <Icon className="w-4 h-4 text-on-surface-variant" />
              </div>
              <span className={cn("text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded-md", tagClass)}>
                {tag}
              </span>
            </div>

            <div>
              <p className="text-sm font-semibold text-on-surface" style={{ fontFamily: "var(--font-manrope)" }}>
                {title}
              </p>
              <p className="text-xs text-on-surface-variant mt-0.5 leading-relaxed">{subtitle}</p>
            </div>

            <button
              className="mt-auto flex items-center gap-1 text-xs font-medium text-primary opacity-0 group-hover:opacity-100 transition-opacity"
              onClick={(e) => { e.stopPropagation(); onAction?.(actionId); }}
            >
              {action}
              <ArrowRight className="w-3 h-3" />
            </button>
          </div>
        ))}
      </div>
    </section>
  );
}
