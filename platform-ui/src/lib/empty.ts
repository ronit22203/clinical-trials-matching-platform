import type { ExecutionLog } from "./types/audit";
import type { AgentConfig, MetricsSnapshot } from "./types/agent";

export const emptyExecutionLog: ExecutionLog = {
  executionId: "",
  model: "",
  latencyMs: 0,
  toolsCalled: [],
  tokensInput: 0,
  tokensOutput: 0,
  gitCommit: "",
  routerIntent: "langgraph",
  entries: [],
};

export const emptyMetrics: MetricsSnapshot = {
  recallAt5: 0,
  ndcgAt5: 0,
  latencyMs: 0,
  costPerRun: 0,
  history: [],
};

export const defaultAgentConfig: AgentConfig = {
  modelName: "",
  temperature: 0.1,
  maxTokens: 2048,
  runtime: "langgraph",
  systemPromptSummary: "",
  tools: [],
};
