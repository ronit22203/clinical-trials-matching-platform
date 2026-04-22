export type EligibilityStatus = "eligible" | "partial" | "excluded";

export interface Criterion {
  id: string;
  text: string;
  met: boolean | null; // null = not enough data
}

export interface Trial {
  id: string;
  nctId: string;
  name: string;
  phase: string;
  sponsor: string;
  matchScore: number; // 0–100
  status: EligibilityStatus;
  inclusionCriteria: Criterion[];
  exclusionCriteria: Criterion[];
  decisionExplanation: string;
}
