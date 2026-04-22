"use client";

import { Map, GitCompare, AlertTriangle, FileBarChart } from "lucide-react";

const ACTIONS = [
  {
    id: "eligibility",
    label: "View Eligibility Criteria Mapping",
    icon: Map,
    prompt: "Show me the full eligibility criteria mapping for this patient",
  },
  {
    id: "compare",
    label: "Compare Top Trials",
    icon: GitCompare,
    prompt: "Compare the top 3 matched trials side by side",
  },
  {
    id: "contraindications",
    label: "View Contraindications",
    icon: AlertTriangle,
    prompt: "Are there any contraindications between current medications and trial therapies?",
  },
  {
    id: "report",
    label: "Generate Summary Report",
    icon: FileBarChart,
    prompt: "Generate a clinical summary report for this case",
  },
] as const;

interface QuickActionsProps {
  onAction?: (prompt: string) => void;
}

export default function QuickActions({ onAction }: QuickActionsProps) {
  return (
    <section className="px-6 pb-4">
      <h2
        className="text-[11px] uppercase tracking-[0.08em] text-on-surface-variant mb-3"
        style={{ fontFamily: "var(--font-manrope)" }}
      >
        Quick Actions
      </h2>

      <div className="flex flex-wrap gap-2">
        {ACTIONS.map(({ id, label, icon: Icon, prompt }) => (
          <button
            key={id}
            onClick={() => onAction?.(prompt)}
            className="flex items-center gap-2 px-3 py-2 rounded-xl bg-surface-container hover:bg-surface-high text-sm text-on-surface-variant hover:text-on-surface transition-colors"
          >
            <Icon className="w-3.5 h-3.5 shrink-0" />
            {label}
          </button>
        ))}
      </div>
    </section>
  );
}
