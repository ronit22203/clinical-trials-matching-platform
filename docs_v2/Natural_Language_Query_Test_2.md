# Comprehensive Test Suite: Hybrid Medical GraphRAG Pipeline

## Phase 1: Ingestion & OCR Extraction Validation

*Purpose: To verify that the ingestion layer accurately extracts text, layout, and medical terminology from scanned PDFs or clinical images before they hit the databases.*

1. **The Artifact Test:** "Extract the exact prescribed dosage and administration route from `[Scanned_Prescription_Image_01]`."
   * *Goal:* Verify the OCR engine correctly handles messy layouts, medical abbreviations, and numerical data without hallucinating standard dosages.
2. **The Table Reconstruction Test:** "Summarize the patient's lipid panel results from the table on page 3 of `[Clinical_Lab_Report.pdf]`."
   * *Goal:* Ensure the OCR maintains tabular structure and row/column relationships, preventing the vectorization of garbled, unformatted text strings.
3. **The Confidence Threshold Test:** "Identify any illegible or low-confidence medical terms extracted from the attending physician's handwritten notes in `[Discharge_Summary_04]`."
   * *Goal:* Test the pipeline's error-handling. Does it flag low-confidence OCR reads, or does it confidently ingest garbage data into the graph?

## Phase 2: Vector Retrieval Isolation (Semantic Search)

*Purpose: To isolate and test the vector database's ability to retrieve context based strictly on semantic meaning, bypassing the graph structure.*

1. **The Broad Symptom Search:** "Find all clinical notes describing patients experiencing 'atypical chest discomfort' or 'heavy feeling in the sternum' without using the word 'angina'."
   * *Goal:* Validate the embedding model's ability to cluster semantically similar clinical presentations.
2. **The Procedural Nuance Test:** "Retrieve protocols detailing the management of post-operative bleeding in minimally invasive cardiac surgeries."
   * *Goal:* Test the vector database's precision in returning highly specific medical protocols without relying on exact entity matches.

## Phase 3: Graph Traversal Isolation (Relational Search)

*Purpose: To isolate the graph database and verify that nodes (entities) and edges (relationships) are correctly mapped and traversable.*

1. **The Direct Entity Linkage Test:** "List all medications currently prescribed to `[Patient_ID_A]` that are known to interact with `[Drug_Name_B]`."
   * *Goal:* Verify exact edge traversal between Patient -> Medication -> Contraindication nodes.
2. **The Multi-Hop Diagnostic Pathway:** "Trace the diagnostic pathway from `[Symptom_X]` to `[Diagnosis_Y]` across all patients in the ward, and identify the most common intermediate test ordered."
   * *Goal:* Force the graph to execute a multi-hop traversal and aggregate node data across a specific population subset.
3. **The Orphan Node Audit:** "Identify any 'Physician' nodes in the system that do not have an active 'Treated' relationship with a 'Patient' node."
   * *Goal:* Test data integrity and graph completeness.

## Phase 4: Hybrid Execution (The Crucible)

*Purpose: To force the orchestrator to intelligently route the query, utilizing both the semantic flexibility of the vector database and the rigid logic of the graph database simultaneously.*

1. **The Unstructured-to-Structured Bridge:** "Find all patients diagnosed with `[Condition_A]` (Graph Traversal) whose scanned triage notes describe 'rapid, shallow breathing' (Vector/OCR Search)."
   * *Goal:* The system must filter by a hard graph constraint and then perform a semantic vector search within that isolated sub-graph.
2. **The Guideline Conflict Test:** "According to the ingested clinical guidelines, what is the standard treatment for `[Disease_X]`, and which specific patients in our database are currently receiving off-label alternatives?"
   * *Goal:* The pipeline must semantically retrieve the standard of care from unstructured texts, then traverse the graph to compare it against structured patient medication records.
3. **The Longitudinal Image-Aware Query:** "Review the historical progression of `[Patient_ID_C]`'s lung capacity. Compare the unstructured radiologist summaries from `[Date_1]` to `[Date_2]` and cross-reference with the active medication graph during that same window."
   * *Goal:* This is the ultimate test. It requires temporal reasoning, OCR/image text extraction, semantic comparison of sequential summaries, and graph traversal of medication history, all synthesized into a single response.
