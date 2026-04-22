export type AuditStepType =
  | "query_submitted"
  | "tool_called"
  | "data_retrieved"
  | "hitl_pending"
  | "final_decision";

export interface AuditEntry {
  id: string;
  step: AuditStepType;
  label: string;
  timestamp: string; // ISO
  durationMs?: number;
  toolName?: string;
  rawJson: Record<string, unknown>;
}

export interface ExecutionLog {
  executionId: string;
  model: string;
  latencyMs: number;
  toolsCalled: string[];
  tokensInput: number;
  tokensOutput: number;
  gitCommit: string;
  routerIntent: "langgraph" | "temporal";
  entries: AuditEntry[];
}
