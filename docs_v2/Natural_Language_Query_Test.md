**Core Trial Matching (the primary use case)**

These test if your retrieval + graph reasoning actually surfaces relevant studies:

- *"58-year-old male, ICU, suspected septic shock, on norepinephrine, lactate 4.2 — are there any trials I should consider enrolling him in?"*
- *"My patient has treatment-resistant sepsis, already failed broad-spectrum antibiotics after 72 hours. What trials are looking at adjunct therapies?"*
- *"Looking for active trials on early goal-directed therapy alternatives for sepsis patients in the ED."*
- *"Are there any immunomodulation trials for sepsis patients with immunocompromised status? Patient has CLL."*
- *"Patient is post-cardiac surgery, developed sepsis on day 3, vasopressor dependent. Any perioperative sepsis trials?"*

---

**Evidence & Research Lookup (tests RAG over your ingested PDFs)**

These check if MARA can synthesize across documents:

- *"What does recent literature say about SOFA vs SIRS for predicting sepsis mortality?"*
- *"Has anyone validated sepsis prediction models outside of academic medical centers?"*
- *"What's the evidence on 1-hour vs 3-hour sepsis bundles — is there a survival difference?"*
- *"Summarize what's known about care-process leakage in sepsis ML models."*
- *"What do the MIMIC-based sepsis studies say about antibiotic timing and outcomes?"*

---

**Eligibility Filtering (stress-tests your graph + criteria matching)**

These push the system to reason about inclusion/exclusion criteria:

- *"My patient is 82 years old with stage 4 CKD — which trials would automatically exclude her?"*
- *"Are there any sepsis trials that specifically include pediatric or elderly populations?"*
- *"Patient is on anticoagulation for AFib — does that exclude them from most sepsis bundle trials?"*
- *"I have a pregnant patient with chorioamnionitis and early sepsis — any trials she could qualify for?"*
- *"Patient previously enrolled in a sepsis trial 6 months ago — would that disqualify them from current trials?"*

---

**Ambiguous / Fuzzy Queries (tests robustness of your NL understanding)**

These are vague or imprecise, like real clinician inputs:

- *"Anything new on sepsis and gut microbiome?"*
- *"Is there something for sepsis patients who keep crashing despite fluids and pressors?"*
- *"What are people trying for cytokine storm in sepsis these days?"*
- *"Any trials for preventing sepsis in high-risk ICU patients?"*
- *"We're seeing a lot of fungal sepsis — is there trial activity there?"*

---

**Negative / Out-of-Scope (tests graceful failure)**

These check if your system knows when it *can't* match:

- *"Are there trials for sepsis in neonates?"* (likely out of scope for adult ICU focus)
- *"What trials are recruiting right now in India?"* (location filter it may not support)
- *"Find me a trial for sepsis with a placebo arm only, phase III, published after 2024."* (complex filter combo)
