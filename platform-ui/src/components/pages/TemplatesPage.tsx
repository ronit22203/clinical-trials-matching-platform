"use client";

import { Copy, Play } from "lucide-react";

interface Template {
  id: string;
  name: string;
  description: string;
  prompt: string;
  tools: string[];
}

interface TemplatesPageProps {
  templates: Template[];
  onRun?: (prompt: string) => void;
}

export default function TemplatesPage({ templates, onRun }: TemplatesPageProps) {
  return (
    <div className="p-6 space-y-5 max-w-3xl">
      <div>
        <h1
          className="text-xl font-bold text-on-surface mb-1"
          style={{ fontFamily: "var(--font-manrope)" }}
        >
          Query Templates
        </h1>
        <p className="text-sm text-on-surface-variant">
          Pre-built prompts for clinical trial matching workflows
        </p>
      </div>

      <div className="space-y-3">
        {templates.map((t) => (
          <div
            key={t.id}
            className="rounded-2xl bg-surface-lowest ambient-shadow p-5 group"
          >
            <div className="flex items-start justify-between gap-3 mb-2">
              <div>
                <p
                  className="text-sm font-semibold text-on-surface"
                  style={{ fontFamily: "var(--font-manrope)" }}
                >
                  {t.name}
                </p>
                <p className="text-xs text-on-surface-variant mt-0.5">{t.description}</p>
              </div>
              <div className="flex gap-1.5 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
                <button
                  onClick={() => navigator.clipboard.writeText(t.prompt)}
                  className="p-1.5 rounded-lg bg-surface-container hover:bg-surface-high text-on-surface-variant transition-colors"
                  title="Copy prompt"
                >
                  <Copy className="w-3.5 h-3.5" />
                </button>
                <button
                  onClick={() => onRun?.(t.prompt)}
                  className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg btn-primary-gradient text-white text-xs font-medium"
                >
                  <Play className="w-3 h-3" />
                  Run
                </button>
              </div>
            </div>

            {/* Prompt preview */}
            <div className="mt-3 rounded-xl bg-surface-container px-3 py-2 border-l-2 border-primary-fixed-dim">
              <p className="text-xs font-mono text-on-surface-variant">{t.prompt}</p>
            </div>

            {/* Tools */}
            <div className="flex flex-wrap gap-1 mt-3">
              {t.tools.map((tool) => (
                <span
                  key={tool}
                  className="text-[10px] px-1.5 py-0.5 rounded-md bg-[rgba(0,80,80,0.08)] text-primary uppercase tracking-wide font-medium"
                >
                  {tool}
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
