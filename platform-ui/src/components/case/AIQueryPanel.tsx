"use client";

import { useState, useRef, useEffect } from "react";
import { cn } from "@/lib/utils";
import { Send, Zap, GitBranch, Stethoscope } from "lucide-react";
import { queryAgent, type QueryResponse } from "@/lib/api/client";

type Mode = "fast" | "auditable";
type ToolId = "pubmed" | "clinicaltrials" | "graphrag";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  tools?: string[];
}

const SUGGESTED_PROMPTS = [
  "Match this patient to relevant clinical trials",
  "Why is the top-ranked trial selected?",
  "Show exclusion criteria conflicts",
  "List supporting evidence for this match",
] as const;

const TOOL_LABELS: Record<ToolId, string> = {
  pubmed: "PubMed",
  clinicaltrials: "ClinicalTrials.gov",
  graphrag: "GraphRAG",
};

export default function AIQueryPanel({
  onQueryComplete,
}: {
  onQueryComplete?: (result: QueryResponse) => void;
}) {
  const [mode, setMode] = useState<Mode>("fast");
  const [activeTools, setActiveTools] = useState<Set<ToolId>>(
    new Set(["pubmed", "clinicaltrials", "graphrag"])
  );
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  function toggleTool(tool: ToolId) {
    setActiveTools((prev) => {
      const next = new Set(prev);
      next.has(tool) ? next.delete(tool) : next.add(tool);
      return next;
    });
  }

  async function handleSubmit(text?: string) {
    const query = (text ?? input).trim();
    if (!query || isStreaming) return;

    const userMsg: Message = { id: `u${Date.now()}`, role: "user", content: query };
    setMessages((m) => [...m, userMsg]);
    setInput("");
    setIsStreaming(true);

    const assistantId = `a${Date.now()}`;
    try {
      const result = await queryAgent({
        query,
        tools: Array.from(activeTools),
        mode: mode === "auditable" ? "temporal" : "langgraph",
      });
      setMessages((m) => {
        const filtered = m.filter((x) => x.id !== assistantId);
        return [
          ...filtered,
          {
            id: assistantId,
            role: "assistant",
            content: result.synthesis,
            tools: result.executionLog.toolsCalled,
          },
        ];
      });
      onQueryComplete?.(result);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setMessages((m) => [
        ...m,
        { id: assistantId, role: "assistant", content: `⚠️ API error: ${msg}` },
      ]);
    }

    setIsStreaming(false);
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  }

  return (
    <section className="px-6 pb-6 flex-1 flex flex-col min-h-0">
      {/* Chat thread */}
      {messages.length > 0 && (
        <div className="flex-1 overflow-y-auto mb-4 space-y-4 min-h-0 max-h-[360px] pr-1">
          {messages.map((msg) => (
            <div
              key={msg.id}
              className={cn(
                "rounded-2xl p-4 text-sm leading-relaxed",
                msg.role === "user"
                  ? "bg-surface-high text-on-surface ml-8"
                  : "ghost-border text-on-surface mr-4"
              )}
            >
              {msg.role === "assistant" && msg.tools && (
                <div className="flex flex-wrap gap-1 mb-2">
                  {msg.tools.map((t) => (
                    <span
                      key={t}
                      className="text-[10px] px-1.5 py-0.5 rounded-md bg-surface-container text-on-surface-variant uppercase tracking-wide"
                    >
                      {TOOL_LABELS[t as ToolId] ?? t}
                    </span>
                  ))}
                </div>
              )}
              <p className="whitespace-pre-wrap">{msg.content}</p>
            </div>
          ))}
          <div ref={messagesEndRef} />
        </div>
      )}

      {/* Suggested prompts (show when empty) */}
      {messages.length === 0 && (
        <div className="flex flex-wrap gap-2 mb-4">
          {SUGGESTED_PROMPTS.map((p) => (
            <button
              key={p}
              onClick={() => handleSubmit(p)}
              className="px-3 py-1.5 rounded-xl bg-surface-container hover:bg-surface-high text-xs text-on-surface-variant hover:text-on-surface transition-colors text-left"
            >
              {p}
            </button>
          ))}
        </div>
      )}

      {/* Floating glass input */}
      <div className="glass rounded-2xl ambient-shadow border border-surface-highest p-3">
        {/* Mode + tool toggles */}
        <div className="flex items-center gap-2 mb-2 flex-wrap">
          <div className="flex items-center gap-1 bg-surface-container rounded-lg p-0.5">
            <button
              onClick={() => setMode("fast")}
              className={cn(
                "flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-medium transition-colors",
                mode === "fast"
                  ? "bg-white text-primary shadow-sm"
                  : "text-on-surface-variant hover:text-on-surface"
              )}
            >
              <Zap className="w-3 h-3" />
              Fast
            </button>
            <button
              onClick={() => setMode("auditable")}
              className={cn(
                "flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-medium transition-colors",
                mode === "auditable"
                  ? "bg-white text-tertiary shadow-sm"
                  : "text-on-surface-variant hover:text-on-surface"
              )}
            >
              <GitBranch className="w-3 h-3" />
              Auditable
            </button>
          </div>

          <div className="h-4 w-px bg-surface-highest" />

          {(Object.keys(TOOL_LABELS) as ToolId[]).map((tool) => (
            <button
              key={tool}
              onClick={() => toggleTool(tool)}
              className={cn(
                "px-2 py-1 rounded-lg text-[11px] font-medium transition-colors",
                activeTools.has(tool)
                  ? "bg-[rgba(0,80,80,0.08)] text-primary"
                  : "bg-surface-container text-on-surface-variant opacity-50"
              )}
            >
              {TOOL_LABELS[tool]}
            </button>
          ))}
        </div>

        {/* Input row */}
        <div className="flex items-end gap-2">
          <Stethoscope className="w-4 h-4 text-on-surface-variant mb-2 shrink-0" />
          <textarea
            ref={textareaRef}
            rows={1}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask about trial eligibility, evidence, or patient fit…"
            className="flex-1 resize-none bg-transparent text-sm text-on-surface placeholder-on-surface-variant/50 outline-none leading-relaxed"
            style={{ maxHeight: 120 }}
          />
          <button
            onClick={() => handleSubmit()}
            disabled={!input.trim() || isStreaming}
            className={cn(
              "p-2 rounded-xl transition-colors shrink-0",
              input.trim() && !isStreaming
                ? "btn-primary-gradient text-white hover:opacity-90"
                : "bg-surface-container text-on-surface-variant opacity-50"
            )}
          >
            <Send className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </section>
  );
}
