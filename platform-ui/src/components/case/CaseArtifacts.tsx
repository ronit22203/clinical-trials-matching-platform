"use client";

import { FileText, Code2, ListOrdered, BookMarked, Terminal, ArrowRight } from "lucide-react";
import { cn } from "@/lib/utils";

const ARTIFACTS = [
  {
    id: "record",
    title: "Patient Record",
    subtitle: "VasquezNewton_990219.pdf",
    icon: FileText,
    tag: "PDF",
    tagClass: "bg-[rgba(0,80,80,0.08)] text-primary",
    action: "View",
  },
  {
    id: "profile",
    title: "Clinical Profile",
    subtitle: "Extracted JSON — 10 attributes",
    icon: Code2,
    tag: "JSON",
    tagClass: "bg-[rgba(0,73,125,0.08)] text-tertiary",
    action: "Inspect",
  },
  {
    id: "matches",
    title: "Trial Matches",
    subtitle: "5 trials ranked by eligibility score",
    icon: ListOrdered,
    tag: "Ranked",
    tagClass: "bg-[rgba(22,163,74,0.08)] text-status-eligible",
    action: "View",
  },
  {
    id: "evidence",
    title: "Evidence Pack",
    subtitle: "5 citations · 3 sources",
    icon: BookMarked,
    tag: "Citations",
    tagClass: "bg-[rgba(132,212,211,0.2)] text-primary",
    action: "Browse",
  },
  {
    id: "logs",
    title: "Execution Logs",
    subtitle: "Run a3f91bc · 4.2s · 3 tools",
    icon: Terminal,
    tag: "JSONL",
    tagClass: "bg-surface-highest text-on-surface-variant",
    action: "Inspect",
  },
];

export default function CaseArtifacts() {
  return (
    <section className="px-6 py-4">
      <h2
        className="text-[11px] uppercase tracking-[0.08em] text-on-surface-variant mb-3"
        style={{ fontFamily: "var(--font-manrope)" }}
      >
        Case Artifacts
      </h2>

      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-5">
        {ARTIFACTS.map(({ id, title, subtitle, icon: Icon, tag, tagClass, action }) => (
          <div
            key={id}
            className={cn(
              "group relative flex flex-col gap-2 p-4 rounded-2xl bg-surface-lowest ambient-shadow cursor-pointer",
              "hover:shadow-[0_8px_24px_rgba(0,80,80,0.09)] transition-shadow"
            )}
          >
            {/* Icon + tag */}
            <div className="flex items-start justify-between">
              <div className="w-9 h-9 rounded-xl bg-surface-container flex items-center justify-center">
                <Icon className="w-4 h-4 text-on-surface-variant" />
              </div>
              <span className={cn("text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded-md", tagClass)}>
                {tag}
              </span>
            </div>

            {/* Text */}
            <div>
              <p className="text-sm font-semibold text-on-surface" style={{ fontFamily: "var(--font-manrope)" }}>
                {title}
              </p>
              <p className="text-xs text-on-surface-variant mt-0.5 leading-relaxed">{subtitle}</p>
            </div>

            {/* Action */}
            <button className="mt-auto flex items-center gap-1 text-xs font-medium text-primary opacity-0 group-hover:opacity-100 transition-opacity">
              {action}
              <ArrowRight className="w-3 h-3" />
            </button>
          </div>
        ))}
      </div>
    </section>
  );
}
