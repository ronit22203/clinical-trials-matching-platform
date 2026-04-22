import type { Citation } from "@/lib/types/evidence";

export const mockCitations: Citation[] = [
  {
    id: "c1",
    title: "Amivantamab plus Lazertinib in Osimertinib-Resistant NSCLC",
    authors: "Park K, Haura EB, Leighl NB, et al.",
    year: 2023,
    source: "pubmed",
    snippet:
      "Among patients with EGFR-mutated NSCLC who had disease progression after osimertinib and chemotherapy, amivantamab–lazertinib combination showed an ORR of 33% (95% CI, 24–43).",
    url: "https://pubmed.ncbi.nlm.nih.gov/37870972/",
    relevanceScore: 0.97,
  },
  {
    id: "c2",
    title: "MARIPOSA-2: Phase 3 Study of Amivantamab + Lazertinib vs Chemotherapy",
    authors: "ClinicalTrials.gov",
    year: 2024,
    source: "clinicaltrials",
    snippet:
      "NCT05112692 — Open-label, randomized, active-controlled Phase 3 study in EGFR-mutated NSCLC after osimertinib. Primary endpoint: Progression-Free Survival.",
    url: "https://clinicaltrials.gov/study/NCT05112692",
    relevanceScore: 0.95,
  },
  {
    id: "c3",
    title: "Resistance Mechanisms to Osimertinib in EGFR-Mutated NSCLC: MET Amplification",
    authors: "Leonetti A, Sharma S, Minari R, et al.",
    year: 2022,
    source: "pubmed",
    snippet:
      "MET amplification was identified in 15–26% of patients with acquired osimertinib resistance. Bispecific EGFR/MET antibodies represent a rational therapeutic strategy for this subset.",
    url: "https://pubmed.ncbi.nlm.nih.gov/35331428/",
    relevanceScore: 0.88,
  },
  {
    id: "c4",
    title: "GraphRAG Knowledge Graph — EGFR Exon 19 Deletion Node",
    authors: "Internal Knowledge Graph (aws-prod-ingestion-graphrag)",
    year: 2026,
    source: "graphrag",
    snippet:
      "Entity: EGFR_Exon19Del → Treatment_Response: [Erlotinib, Gefitinib, Osimertinib] → Resistance_Pathway: [T790M, C797S, MET_AMP]. 847 connected entities, 12,403 relationship edges.",
    url: "#",
    relevanceScore: 0.92,
  },
  {
    id: "c5",
    title: "Nivolumab plus Chemotherapy vs Chemotherapy in Advanced NSCLC: CheckMate 901",
    authors: "Garon EB, Nishio M, Durvalumab Study Group et al.",
    year: 2023,
    source: "pubmed",
    snippet:
      "Nivolumab + chemo significantly improved OS vs chemo alone (mOS 14.1 vs 11.7 months) in all-comers. Benefit observed regardless of EGFR mutation status post-TKI failure.",
    url: "https://pubmed.ncbi.nlm.nih.gov/37270673/",
    relevanceScore: 0.81,
  },
];
