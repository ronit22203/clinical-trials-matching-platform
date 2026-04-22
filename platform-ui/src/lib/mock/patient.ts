import type { PatientCase } from "@/lib/types/patient";

export const mockPatient: PatientCase = {
  id: "990219",
  name: "VasquezNewton",
  status: "matching_complete",
  runtime: "langgraph",
  lastRun: "2026-04-20T12:34:00Z",
  condition: "Non-Small Cell Lung Cancer (NSCLC) — Stage IIIB",
  age: 58,
  gender: "Female",
  ecogScore: 1,
  attributes: [
    { key: "Primary Diagnosis", value: "NSCLC Stage IIIB", category: "diagnosis" },
    { key: "Histology", value: "Adenocarcinoma", category: "diagnosis" },
    { key: "EGFR Mutation", value: "Exon 19 deletion", category: "biomarker" },
    { key: "ALK Status", value: "Negative", category: "biomarker" },
    { key: "PD-L1 Expression", value: "45%", category: "biomarker" },
    { key: "Prior Therapies", value: "Erlotinib (12 months), Carboplatin/Paclitaxel", category: "history" },
    { key: "ECOG Performance Status", value: "1", category: "lab" },
    { key: "eGFR", value: "72 mL/min/1.73m²", category: "lab" },
    { key: "ALT", value: "28 U/L (normal)", category: "lab" },
    { key: "Current Medication", value: "Osimertinib 80mg QD", category: "medication" },
  ],
};

export const mockCases: PatientCase[] = [
  mockPatient,
  {
    id: "880112",
    name: "PatelKumar",
    status: "pending",
    runtime: "temporal",
    lastRun: "2026-04-19T09:15:00Z",
    condition: "Colorectal Cancer — Stage IV",
    age: 64,
    gender: "Male",
    ecogScore: 0,
    attributes: [],
  },
  {
    id: "770334",
    name: "LiuChen",
    status: "in_review",
    runtime: "langgraph",
    lastRun: "2026-04-18T16:42:00Z",
    condition: "Pancreatic Ductal Adenocarcinoma — Stage IIB",
    age: 71,
    gender: "Female",
    ecogScore: 2,
    attributes: [],
  },
];
