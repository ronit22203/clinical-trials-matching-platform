export type EvidenceSource = "pubmed" | "clinicaltrials" | "graphrag";

export interface Citation {
  id: string;
  title: string;
  authors: string;
  year: number;
  source: EvidenceSource;
  snippet: string;
  url: string;
  relevanceScore: number; // 0–1
}
