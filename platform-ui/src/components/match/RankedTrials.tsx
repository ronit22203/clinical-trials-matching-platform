"use client";

import { cn, scoreColor } from "@/lib/utils";
import type { Trial, EligibilityStatus } from "@/lib/types/trial";
import { ChevronRight } from "lucide-react";

const STATUS_LABEL: Record<EligibilityStatus, string> = {
  eligible: "Eligible",
  partial: "Partial",
  excluded: "Excluded",
};

const STATUS_CLASS: Record<EligibilityStatus, string> = {
  eligible: "bg-[rgba(22,163,74,0.1)] text-status-eligible",
  partial: "bg-[rgba(217,119,6,0.1)] text-status-partial",
  excluded: "bg-[rgba(220,38,38,0.1)] text-status-excluded",
};

interface RankedTrialsProps {
  trials: Trial[];
  onSelect?: (trial: Trial) => void;
}

export default function RankedTrials({ trials, onSelect }: RankedTrialsProps) {
  return (
    <div className="space-y-2">
      {trials.map((trial, idx) => (
        <button
          key={trial.id}
          onClick={() => onSelect?.(trial)}
          className="w-full text-left group rounded-2xl bg-surface-lowest ambient-shadow p-4 hover:shadow-[0_8px_24px_rgba(0,80,80,0.09)] transition-shadow"
        >
          {/* Rank + status */}
          <div className="flex items-start justify-between gap-2 mb-2">
            <span className="text-[10px] font-semibold text-on-surface-variant uppercase tracking-widest">
              #{idx + 1}
            </span>
            <span className={cn("text-[10px] font-semibold px-1.5 py-0.5 rounded-md uppercase tracking-wide", STATUS_CLASS[trial.status])}>
              {STATUS_LABEL[trial.status]}
            </span>
          </div>

          {/* Trial name */}
          <p
            className="text-sm font-semibold text-on-surface leading-snug mb-1 line-clamp-2"
            style={{ fontFamily: "var(--font-manrope)" }}
          >
            {trial.name}
          </p>

          {/* NCT ID + phase */}
          <p className="text-xs text-on-surface-variant mb-3">
            {trial.nctId} · {trial.phase}
          </p>

          {/* Score bar */}
          <div className="space-y-1">
            <div className="flex items-center justify-between">
              <span className="text-[10px] uppercase tracking-widest text-on-surface-variant">
                Match Score
              </span>
              <span className={cn("text-sm font-bold tabular-nums", scoreColor(trial.matchScore))}>
                {trial.matchScore}%
              </span>
            </div>
            <div className="h-1.5 rounded-full bg-surface-container overflow-hidden">
              <div
                className={cn(
                  "h-full rounded-full transition-all duration-500",
                  trial.status === "eligible"
                    ? "bg-status-eligible"
                    : trial.status === "partial"
                    ? "bg-status-partial"
                    : "bg-status-excluded"
                )}
                style={{ width: `${trial.matchScore}%` }}
              />
            </div>
          </div>

          {/* Drill-down arrow */}
          <div className="flex items-center justify-end mt-2 opacity-0 group-hover:opacity-100 transition-opacity">
            <span className="text-[10px] text-primary font-medium mr-0.5">View criteria</span>
            <ChevronRight className="w-3 h-3 text-primary" />
          </div>
        </button>
      ))}
    </div>
  );
}
