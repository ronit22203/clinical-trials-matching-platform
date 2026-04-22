"use client";

import { cn, formatTimestamp } from "@/lib/utils";
import type { PatientCase } from "@/lib/types/patient";
import { CheckCircle2, Clock, Zap, GitBranch, Download, PlayCircle, UserCheck } from "lucide-react";

interface CaseHeaderProps {
  patient: PatientCase;
  onRunMatching?: () => void;
  onApprove?: () => void;
  onExport?: () => void;
}

const STATUS_CONFIG = {
  matching_complete: {
    label: "Matching Complete",
    icon: CheckCircle2,
    className: "bg-[rgba(22,163,74,0.1)] text-status-eligible",
  },
  pending: {
    label: "Pending",
    icon: Clock,
    className: "bg-[rgba(217,119,6,0.1)] text-status-partial",
  },
  in_review: {
    label: "In Review",
    icon: Clock,
    className: "bg-[rgba(0,80,80,0.1)] text-primary",
  },
};

const RUNTIME_CONFIG = {
  langgraph: { label: "LangGraph", icon: Zap, className: "text-primary" },
  temporal: { label: "Temporal", icon: GitBranch, className: "text-tertiary" },
};

export default function CaseHeader({
  patient,
  onRunMatching,
  onApprove,
  onExport,
}: CaseHeaderProps) {
  const status = STATUS_CONFIG[patient.status];
  const runtime = RUNTIME_CONFIG[patient.runtime];
  const StatusIcon = status.icon;
  const RuntimeIcon = runtime.icon;

  return (
    <div className="px-6 pt-6 pb-4 bg-surface">
      {/* Top row */}
      <div className="flex items-start justify-between gap-4">
        {/* Left: patient info */}
        <div className="min-w-0">
          <p
            className="text-[11px] uppercase tracking-[0.08em] text-on-surface-variant mb-1"
            style={{ fontFamily: "var(--font-manrope)" }}
          >
            Patient Case
          </p>
          <h1
            className="text-2xl font-bold text-on-surface truncate"
            style={{ fontFamily: "var(--font-manrope)" }}
          >
            {patient.name}
            <span className="ml-2 text-base font-normal text-on-surface-variant">
              ID: {patient.id}
            </span>
          </h1>

          <p className="mt-1 text-sm text-on-surface-variant truncate">
            {patient.condition}
          </p>

          {/* Badges row */}
          <div className="flex flex-wrap items-center gap-2 mt-3">
            {/* Status badge */}
            <span
              className={cn(
                "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium",
                status.className
              )}
            >
              <StatusIcon className="w-3 h-3" />
              {status.label}
            </span>

            {/* Runtime chip */}
            <span
              className={cn(
                "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium bg-surface-container",
                runtime.className
              )}
            >
              <RuntimeIcon className="w-3 h-3" />
              {runtime.label}
            </span>

            {/* Last run */}
            <span className="text-xs text-on-surface-variant">
              Last run:{" "}
              <span className="text-on-surface font-medium">
                {formatTimestamp(patient.lastRun)}
              </span>
            </span>
          </div>
        </div>

        {/* Right: action buttons */}
        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={onExport}
            className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-medium text-on-surface-variant bg-surface-container hover:bg-surface-high transition-colors"
          >
            <Download className="w-3.5 h-3.5" />
            Export PDF
          </button>

          <button
            onClick={onApprove}
            className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-medium text-on-surface bg-surface-container hover:bg-surface-high border border-surface-highest transition-colors"
          >
            <UserCheck className="w-3.5 h-3.5" />
            Approve
          </button>

          <button
            onClick={onRunMatching}
            className="flex items-center gap-1.5 px-4 py-2 rounded-xl text-sm font-semibold text-white btn-primary-gradient hover:opacity-90 transition-opacity ambient-shadow"
          >
            <PlayCircle className="w-4 h-4" />
            Run Matching
          </button>
        </div>
      </div>

      {/* Divider via background shift */}
      <div className="mt-4 h-px bg-surface-highest opacity-70" />
    </div>
  );
}
