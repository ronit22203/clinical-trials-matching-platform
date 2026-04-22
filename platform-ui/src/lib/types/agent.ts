export interface ToolConfig {
  name: string;
  enabled: boolean;
  description: string;
}

export interface AgentConfig {
  modelName: string;
  temperature: number;
  maxTokens: number;
  runtime: "langgraph" | "temporal";
  tools: ToolConfig[];
  systemPromptSummary: string;
}

export interface MetricsSnapshot {
  recallAt5: number;        // 0–1
  ndcgAt5: number;          // 0–1
  latencyMs: number;
  costPerRun: number;       // USD
  history: MetricPoint[];
}

export interface MetricPoint {
  date: string;             // YYYY-MM-DD
  recallAt5: number;
  ndcgAt5: number;
  latencyMs: number;
}
