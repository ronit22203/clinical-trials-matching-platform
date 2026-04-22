"use client";

import { cn } from "@/lib/utils";
import type { Trial } from "@/lib/types/trial";
import type { PatientCase } from "@/lib/types/patient";
import { X, CheckCircle2, XCircle, MinusCircle, CheckCheck, AlertTriangle, Ban } from "lucide-react";

interface TrialDrillDownProps {
  trial: Trial;
  patient: PatientCase;
  onClose: () => void;
}

const DECISION_CONFIG = {
  eligible: {
    icon: CheckCheck,
    label: "Eligible",
    emoji: "✅",
    className: "border-status-eligible bg-[rgba(22,163,74,0.06)]",
    textClass: "text-status-eligible",
    badgeClass: "bg-[rgba(22,163,74,0.1)] text-status-eligible",
  },
  partial: {
    icon: AlertTriangle,
    label: "Partial Match",
    emoji: "⚠️",
    className: "border-status-partial bg-[rgba(217,119,6,0.06)]",
    textClass: "text-status-partial",
    badgeClass: "bg-[rgba(217,119,6,0.1)] text-status-partial",
  },
  excluded: {
    icon: Ban,
    label: "Not Eligible",
    emoji: "❌",
    className: "border-status-excluded bg-[rgba(220,38,38,0.06)]",
    textClass: "text-status-excluded",
    badgeClass: "bg-[rgba(220,38,38,0.1)] text-status-excluded",
  },
};

export default function TrialDrillDown({ trial, patient, onClose }: TrialDrillDownProps) {
  const decision = DECISION_CONFIG[trial.status];
  const DecisionIcon = decision.icon;

  return (
    /* Backdrop */
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: "rgba(26,28,28,0.4)", backdropFilter: "blur(4px)" }}
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="bg-surface-lowest rounded-3xl ambient-shadow w-full max-w-5xl max-h-[90vh] flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-start justify-between px-6 py-4 border-b border-surface-highest">
          <div>
            <p className="text-[10px] uppercase tracking-widest text-on-surface-variant mb-1">
              {trial.nctId} · {trial.phase}
            </p>
            <h2
              className="text-lg font-bold text-on-surface leading-snug max-w-2xl"
              style={{ fontFamily: "var(--font-manrope)" }}
            >
              {trial.name}
            </h2>
            <p className="text-xs text-on-surface-variant mt-0.5">{trial.sponsor}</p>
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-xl text-on-surface-variant hover:bg-surface-container transition-colors shrink-0"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Split body */}
        <div className="flex-1 overflow-hidden flex">
          {/* Left: Criteria */}
          <div className="flex-1 overflow-y-auto p-6 space-y-6 border-r border-surface-highest">
            {/* Inclusion */}
            <div>
              <p
                className="text-[11px] uppercase tracking-[0.08em] text-on-surface-variant mb-3"
                style={{ fontFamily: "var(--font-manrope)" }}
              >
                Inclusion Criteria
              </p>
              <div className="space-y-2">
                {trial.inclusionCriteria.map((c) => (
                  <div key={c.id} className="flex items-start gap-2">
                    {c.met === true ? (
                      <CheckCircle2 className="w-4 h-4 text-status-eligible mt-0.5 shrink-0" />
                    ) : c.met === false ? (
                      <XCircle className="w-4 h-4 text-status-excluded mt-0.5 shrink-0" />
                    ) : (
                      <MinusCircle className="w-4 h-4 text-on-surface-variant mt-0.5 shrink-0" />
                    )}
                    <p
                      className={cn(
                        "text-sm leading-snug",
                        c.met === true
                          ? "text-on-surface"
                          : c.met === false
                          ? "text-status-excluded"
                          : "text-on-surface-variant"
                      )}
                    >
                      {c.text}
                    </p>
                  </div>
                ))}
              </div>
            </div>

            {/* Exclusion */}
            <div>
              <p
                className="text-[11px] uppercase tracking-[0.08em] text-on-surface-variant mb-3"
                style={{ fontFamily: "var(--font-manrope)" }}
              >
                Exclusion Criteria
              </p>
              <div className="space-y-2">
                {trial.exclusionCriteria.map((c) => (
                  <div key={c.id} className="flex items-start gap-2">
                    {c.met === true ? (
                      <XCircle className="w-4 h-4 text-status-excluded mt-0.5 shrink-0" />
                    ) : (
                      <CheckCircle2 className="w-4 h-4 text-status-eligible mt-0.5 shrink-0" />
                    )}
                    <p
                      className={cn(
                        "text-sm leading-snug",
                        c.met === true ? "text-status-excluded font-medium" : "text-on-surface"
                      )}
                    >
                      {c.text}
                      {c.met === true && (
                        <span className="ml-1.5 text-xs font-normal text-status-excluded">
                          ← CONFLICT
                        </span>
                      )}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Right: Patient attributes */}
          <div className="w-[300px] shrink-0 overflow-y-auto p-6 space-y-3">
            <p
              className="text-[11px] uppercase tracking-[0.08em] text-on-surface-variant mb-3"
              style={{ fontFamily: "var(--font-manrope)" }}
            >
              Patient: {patient.name}
            </p>

            {patient.attributes.map((attr) => {
              const isHighlighted =
                attr.category === "biomarker" || attr.category === "diagnosis";
              return (
                <div
                  key={attr.key}
                  className={cn(
                    "rounded-xl px-3 py-2",
                    isHighlighted ? "bg-[rgba(132,212,211,0.15)]" : "bg-surface-container"
                  )}
                >
                  <p className="text-[10px] uppercase tracking-widest text-on-surface-variant">
                    {attr.key}
                  </p>
                  <p
                    className={cn(
                      "text-sm font-semibold mt-0.5",
                      isHighlighted ? "text-primary" : "text-on-surface"
                    )}
                  >
                    {attr.value}
                  </p>
                </div>
              );
            })}
          </div>
        </div>

        {/* Decision Panel */}
        <div
          className={cn(
            "px-6 py-4 border-t-2 rounded-b-3xl",
            decision.className
          )}
        >
          <div className="flex items-start gap-3">
            <div className={cn("p-2 rounded-xl bg-white/60", decision.textClass)}>
              <DecisionIcon className="w-5 h-5" />
            </div>
            <div className="flex-1">
              <p
                className={cn("text-sm font-bold mb-1", decision.textClass)}
                style={{ fontFamily: "var(--font-manrope)" }}
              >
                {decision.emoji} {decision.label}
              </p>
              <p className="text-xs text-on-surface-variant leading-relaxed">
                {trial.decisionExplanation}
              </p>
            </div>
            <span
              className={cn(
                "text-2xl font-black tabular-nums shrink-0",
                decision.textClass
              )}
              style={{ fontFamily: "var(--font-manrope)" }}
            >
              {trial.matchScore}%
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
