import type { MetricsSnapshot } from "@/lib/types/agent";

export const mockMetrics: MetricsSnapshot = {
  recallAt5: 0.85,
  ndcgAt5: 0.79,
  latencyMs: 4210,
  costPerRun: 0.0031,
  history: [
    { date: "2026-04-14", recallAt5: 0.80, ndcgAt5: 0.72, latencyMs: 5100 },
    { date: "2026-04-15", recallAt5: 0.82, ndcgAt5: 0.74, latencyMs: 4800 },
    { date: "2026-04-16", recallAt5: 0.81, ndcgAt5: 0.73, latencyMs: 4950 },
    { date: "2026-04-17", recallAt5: 0.84, ndcgAt5: 0.77, latencyMs: 4500 },
    { date: "2026-04-18", recallAt5: 0.83, ndcgAt5: 0.76, latencyMs: 4620 },
    { date: "2026-04-19", recallAt5: 0.84, ndcgAt5: 0.78, latencyMs: 4310 },
    { date: "2026-04-20", recallAt5: 0.85, ndcgAt5: 0.79, latencyMs: 4210 },
  ],
};

export const mockAgentConfig = {
  modelName: "ollama/qwen3:1.7b",
  temperature: 0.1,
  maxTokens: 2048,
  runtime: "langgraph" as const,
  systemPromptSummary:
    "Clinical research assistant. Answer with precision. Cite sources. Flag uncertainty explicitly.",
  tools: [
    { name: "pubmed_search", enabled: true, description: "Search PubMed abstracts via NCBI eUtils" },
    { name: "clinical_trials", enabled: true, description: "Query ClinicalTrials.gov v2 API" },
    { name: "graphrag_search", enabled: true, description: "Hybrid vector + graph search over Qdrant/Neo4j" },
    { name: "fda_adverse_events", enabled: false, description: "Query openFDA drug event database" },
    { name: "mcp_filesystem", enabled: false, description: "Read/write files via MCP server" },
  ],
};

export const mockQueryTemplates = [
  {
    id: "qt1",
    name: "Full Trial Match",
    description: "End-to-end eligibility matching across all active trials",
    prompt: "Match this patient to relevant clinical trials",
    tools: ["pubmed_search", "clinical_trials", "graphrag_search"],
  },
  {
    id: "qt2",
    name: "Trial Ranking Explanation",
    description: "Explain why the top-ranked trial was selected",
    prompt: "Why is Trial NCT05112692 ranked #1 for this patient?",
    tools: ["graphrag_search"],
  },
  {
    id: "qt3",
    name: "Exclusion Conflicts",
    description: "Surface exclusion criteria conflicts across all trials",
    prompt: "Show exclusion criteria conflicts for this patient across all matched trials",
    tools: ["graphrag_search", "clinical_trials"],
  },
  {
    id: "qt4",
    name: "Evidence Pack",
    description: "Generate citations supporting the match rationale",
    prompt: "List supporting evidence and citations for the top trial match",
    tools: ["pubmed_search", "graphrag_search"],
  },
  {
    id: "qt5",
    name: "Contraindication Check",
    description: "Check current medications against trial drug profiles",
    prompt: "Are there any contraindications between current medications and trial therapies?",
    tools: ["pubmed_search", "fda_adverse_events"],
  },
];
