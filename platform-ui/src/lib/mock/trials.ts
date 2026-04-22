import type { Trial } from "@/lib/types/trial";

export const mockTrials: Trial[] = [
  {
    id: "t1",
    nctId: "NCT05112692",
    name: "MARIPOSA-2: Amivantamab + Lazertinib vs Chemotherapy in EGFR NSCLC",
    phase: "Phase III",
    sponsor: "Janssen Research & Development",
    matchScore: 91,
    status: "eligible",
    decisionExplanation:
      "Patient meets all primary inclusion criteria: EGFR exon 19 deletion confirmed, prior osimertinib therapy, ECOG PS 1, adequate organ function. No exclusion conflicts detected.",
    inclusionCriteria: [
      { id: "ic1", text: "EGFR exon 19 deletion or exon 21 L858R mutation", met: true },
      { id: "ic2", text: "Prior treatment with osimertinib or 3rd-gen EGFR TKI", met: true },
      { id: "ic3", text: "ECOG Performance Status 0–1", met: true },
      { id: "ic4", text: "Adequate hepatic function (ALT ≤2.5× ULN)", met: true },
      { id: "ic5", text: "Measurable disease per RECIST 1.1", met: true },
    ],
    exclusionCriteria: [
      { id: "ec1", text: "Prior amivantamab or bispecific EGFR/MET therapy", met: false },
      { id: "ec2", text: "Uncontrolled CNS metastases", met: false },
      { id: "ec3", text: "QTc > 470 ms", met: false },
      { id: "ec4", text: "Active autoimmune disease requiring systemic treatment", met: false },
    ],
  },
  {
    id: "t2",
    nctId: "NCT04427072",
    name: "PAPILLON: Amivantamab + Chemotherapy for EGFR Exon 20 Insertions",
    phase: "Phase III",
    sponsor: "Janssen",
    matchScore: 62,
    status: "partial",
    decisionExplanation:
      "Trial targets EGFR exon 20 insertions specifically. Patient has exon 19 deletion — not the target mutation. Partial match on histology and performance status only.",
    inclusionCriteria: [
      { id: "ic1", text: "EGFR exon 20 insertion mutation", met: false },
      { id: "ic2", text: "Adenocarcinoma histology", met: true },
      { id: "ic3", text: "ECOG PS 0–1", met: true },
      { id: "ic4", text: "No prior EGFR TKI therapy", met: false },
    ],
    exclusionCriteria: [
      { id: "ec1", text: "Prior platinum-based chemotherapy (1st line)", met: true },
      { id: "ec2", text: "Active brain metastases", met: false },
    ],
  },
  {
    id: "t3",
    nctId: "NCT05261399",
    name: "CheckMate 901: Nivolumab + Chemotherapy in Metastatic NSCLC",
    phase: "Phase III",
    sponsor: "Bristol-Myers Squibb",
    matchScore: 78,
    status: "eligible",
    decisionExplanation:
      "Patient is eligible. PD-L1 expression ≥1%, EGFR mutation eligible post-TKI progression. No contraindications to immunotherapy detected.",
    inclusionCriteria: [
      { id: "ic1", text: "Stage IV NSCLC (any histology)", met: true },
      { id: "ic2", text: "PD-L1 ≥ 1%", met: true },
      { id: "ic3", text: "No prior immunotherapy", met: true },
      { id: "ic4", text: "ECOG PS 0–1", met: true },
    ],
    exclusionCriteria: [
      { id: "ec1", text: "Active autoimmune disease", met: false },
      { id: "ec2", text: "Prior checkpoint inhibitor therapy", met: false },
      { id: "ec3", text: "Systemic corticosteroids > 10mg/day prednisone", met: false },
    ],
  },
  {
    id: "t4",
    nctId: "NCT03949634",
    name: "KRYSTAL-12: Adagrasib in KRAS G12C NSCLC",
    phase: "Phase III",
    sponsor: "Mirati Therapeutics",
    matchScore: 18,
    status: "excluded",
    decisionExplanation:
      "Patient does not harbor KRAS G12C mutation — this is the sole eligibility driver. Exclusion is definitive.",
    inclusionCriteria: [
      { id: "ic1", text: "KRAS G12C mutation confirmed", met: false },
      { id: "ic2", text: "Prior platinum-based chemotherapy", met: true },
      { id: "ic3", text: "ECOG PS 0–1", met: true },
    ],
    exclusionCriteria: [
      { id: "ec1", text: "Prior KRAS-targeted therapy", met: false },
      { id: "ec2", text: "Active leptomeningeal disease", met: false },
    ],
  },
  {
    id: "t5",
    nctId: "NCT04644094",
    name: "TROPION-Lung01: Datopotamab deruxtecan vs Docetaxel",
    phase: "Phase III",
    sponsor: "AstraZeneca / Daiichi Sankyo",
    matchScore: 55,
    status: "partial",
    decisionExplanation:
      "Patient meets general criteria but eGFR borderline for protocol requirements. Renal function monitoring required. Recommend nephrology review before enrollment.",
    inclusionCriteria: [
      { id: "ic1", text: "Advanced/metastatic NSCLC (non-squamous)", met: true },
      { id: "ic2", text: "≥1 prior line including platinum-based", met: true },
      { id: "ic3", text: "ECOG PS 0–1", met: true },
      { id: "ic4", text: "eGFR ≥ 80 mL/min/1.73m²", met: false },
    ],
    exclusionCriteria: [
      { id: "ec1", text: "Uncontrolled ILD or pneumonitis", met: false },
      { id: "ec2", text: "Active CNS metastases", met: false },
    ],
  },
];
