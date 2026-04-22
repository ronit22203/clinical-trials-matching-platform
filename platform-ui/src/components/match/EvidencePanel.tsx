"use client";

import type { Citation, EvidenceSource } from "@/lib/types/evidence";
import { cn } from "@/lib/utils";
import { ExternalLink } from "lucide-react";

const SOURCE_CONFIG: Record<
  EvidenceSource,
  { label: string; className: string }
> = {
  pubmed: {
    label: "PubMed",
    className: "bg-[rgba(0,80,80,0.08)] text-primary",
  },
  clinicaltrials: {
    label: "ClinicalTrials",
    className: "bg-[rgba(0,73,125,0.08)] text-tertiary",
  },
  graphrag: {
    label: "GraphRAG",
    className: "bg-[rgba(132,212,211,0.2)] text-primary",
  },
};

interface EvidencePanelProps {
  citations: Citation[];
}

export default function EvidencePanel({ citations }: EvidencePanelProps) {
  return (
    <div className="space-y-2">
      {citations.map((c) => {
        const src = SOURCE_CONFIG[c.source];
        return (
          <div
            key={c.id}
            className="rounded-2xl bg-surface-lowest ambient-shadow p-4 space-y-2"
          >
            {/* Source tag + relevance */}
            <div className="flex items-center justify-between">
              <span
                className={cn(
                  "text-[10px] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded-md",
                  src.className
                )}
              >
                {src.label}
              </span>
              <span className="text-[10px] text-on-surface-variant">
                Relevance{" "}
                <span className="font-semibold text-on-surface">
                  {Math.round(c.relevanceScore * 100)}%
                </span>
              </span>
            </div>

            {/* Title */}
            <p
              className="text-sm font-semibold text-on-surface leading-snug"
              style={{ fontFamily: "var(--font-manrope)" }}
            >
              {c.title}
            </p>

            {/* Authors + year */}
            <p className="text-xs text-on-surface-variant">
              {c.authors} · {c.year}
            </p>

            {/* Snippet */}
            <p className="text-xs text-on-surface-variant leading-relaxed border-l-2 border-primary-fixed-dim pl-2">
              {c.snippet}
            </p>

            {/* Link */}
            {c.url !== "#" && (
              <a
                href={c.url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-xs text-primary hover:underline font-medium"
              >
                Open source <ExternalLink className="w-3 h-3" />
              </a>
            )}
          </div>
        );
      })}
    </div>
  );
}
