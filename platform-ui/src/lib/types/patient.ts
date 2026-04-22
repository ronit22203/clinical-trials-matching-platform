export interface PatientCase {
  id: string;
  name: string;
  status: "matching_complete" | "pending" | "in_review";
  runtime: "langgraph" | "temporal";
  lastRun: string; // ISO timestamp
  condition: string;
  age: number;
  gender: string;
  ecogScore: number;
  attributes: PatientAttribute[];
}

export interface PatientAttribute {
  key: string;
  value: string;
  category: "diagnosis" | "biomarker" | "history" | "lab" | "medication";
}
