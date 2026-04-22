"use client";

import { useState } from "react";
import type { AgentConfig } from "@/lib/types/agent";
import { cn } from "@/lib/utils";
import { Zap, GitBranch } from "lucide-react";

const MODEL_OPTIONS = [
  "ollama/qwen3:1.7b",
  "ollama/qwen3:8b",
  "ollama/llama3.1:8b",
  "litellm/gpt-4o-mini",
  "litellm/claude-3-haiku",
];

interface ConfigPanelProps {
  config: AgentConfig;
  onChange?: (updated: AgentConfig) => void;
}

export default function ConfigPanel({ config, onChange }: ConfigPanelProps) {
  const [local, setLocal] = useState<AgentConfig>(config);

  function update(patch: Partial<AgentConfig>) {
    const next = { ...local, ...patch };
    setLocal(next);
    onChange?.(next);
  }

  function toggleTool(name: string) {
    update({
      tools: local.tools.map((t) =>
        t.name === name ? { ...t, enabled: !t.enabled } : t
      ),
    });
  }

  return (
    <div className="p-6 space-y-6 max-w-2xl">
      <div>
        <h1
          className="text-xl font-bold text-on-surface mb-1"
          style={{ fontFamily: "var(--font-manrope)" }}
        >
          Agent Config
        </h1>
        <p className="text-sm text-on-surface-variant">
          YAML-backed · changes are hot-reloaded by the agent runtime
        </p>
      </div>

      <div className="rounded-2xl bg-surface-lowest ambient-shadow p-5 space-y-6">
        {/* Model selection */}
        <div>
          <label className="text-[11px] uppercase tracking-[0.08em] text-on-surface-variant block mb-2">
            Model
          </label>
          <select
            value={local.modelName}
            onChange={(e) => update({ modelName: e.target.value })}
            className="w-full rounded-xl bg-surface-container border-0 text-sm text-on-surface px-3 py-2.5 outline-none focus:ring-1 focus:ring-primary"
          >
            {MODEL_OPTIONS.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </div>

        {/* Runtime toggle */}
        <div>
          <label className="text-[11px] uppercase tracking-[0.08em] text-on-surface-variant block mb-2">
            Runtime
          </label>
          <div className="flex gap-2">
            {(["langgraph", "temporal"] as const).map((r) => (
              <button
                key={r}
                onClick={() => update({ runtime: r })}
                className={cn(
                  "flex items-center gap-1.5 px-3 py-2 rounded-xl text-sm font-medium transition-colors",
                  local.runtime === r
                    ? "btn-primary-gradient text-white"
                    : "bg-surface-container text-on-surface-variant hover:bg-surface-high"
                )}
              >
                {r === "langgraph" ? (
                  <Zap className="w-3.5 h-3.5" />
                ) : (
                  <GitBranch className="w-3.5 h-3.5" />
                )}
                {r === "langgraph" ? "LangGraph (Fast)" : "Temporal (Auditable)"}
              </button>
            ))}
          </div>
        </div>

        {/* Temperature */}
        <div>
          <label className="text-[11px] uppercase tracking-[0.08em] text-on-surface-variant block mb-2">
            Temperature:{" "}
            <span className="font-mono text-on-surface">{local.temperature.toFixed(2)}</span>
          </label>
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={local.temperature}
            onChange={(e) => update({ temperature: parseFloat(e.target.value) })}
            className="w-full accent-primary"
          />
          <div className="flex justify-between text-[10px] text-on-surface-variant mt-1">
            <span>0.00 — Deterministic</span>
            <span>1.00 — Creative</span>
          </div>
        </div>

        {/* Max tokens */}
        <div>
          <label className="text-[11px] uppercase tracking-[0.08em] text-on-surface-variant block mb-2">
            Max Tokens:{" "}
            <span className="font-mono text-on-surface">{local.maxTokens}</span>
          </label>
          <input
            type="range"
            min={256}
            max={8192}
            step={256}
            value={local.maxTokens}
            onChange={(e) => update({ maxTokens: parseInt(e.target.value) })}
            className="w-full accent-primary"
          />
        </div>

        {/* Tools */}
        <div>
          <label className="text-[11px] uppercase tracking-[0.08em] text-on-surface-variant block mb-3">
            Tools
          </label>
          <div className="space-y-2">
            {local.tools.map((tool) => (
              <div
                key={tool.name}
                className="flex items-center justify-between p-3 rounded-xl bg-surface-container"
              >
                <div>
                  <p className="text-sm font-medium text-on-surface font-mono">{tool.name}</p>
                  <p className="text-xs text-on-surface-variant mt-0.5">{tool.description}</p>
                </div>
                <button
                  onClick={() => toggleTool(tool.name)}
                  className={cn(
                    "relative w-10 h-5 rounded-full transition-colors shrink-0 ml-4",
                    tool.enabled ? "bg-primary" : "bg-surface-highest"
                  )}
                  role="switch"
                  aria-checked={tool.enabled}
                >
                  <span
                    className={cn(
                      "absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform",
                      tool.enabled && "translate-x-5"
                    )}
                  />
                </button>
              </div>
            ))}
          </div>
        </div>

        {/* System prompt summary */}
        <div>
          <label className="text-[11px] uppercase tracking-[0.08em] text-on-surface-variant block mb-2">
            System Prompt
          </label>
          <div className="rounded-xl bg-surface-container p-3 border-l-2 border-primary-fixed-dim">
            <p className="text-xs text-on-surface-variant leading-relaxed italic">
              "{local.systemPromptSummary}"
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
