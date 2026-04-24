## 1. Retrieval Metrics (Qdrant + Neo4j → Top-K Chunks)

You have 20 queries. For each query, the system returns a ranked list of chunks (up to K=10). The golden file tells you which chunks are relevant (2 = highly relevant, 1 = partially relevant).

### Recall@K

**Formula:**
`Recall@K = (number of relevant chunks in top K) / (total relevant chunks for that query)`

**What it means:** Of all the chunks that *should* have been found, how many did the system actually retrieve in the top K?

- K=1 → Did the top result contain the answer?
- K=5 → Did the answer appear within the first 5?

**Why it matters:** A clinician scanning results wants the answer quickly. Recall@1 > 80% means they rarely need to scroll.

### Precision@K

**Formula:**
`Precision@K = (number of relevant chunks in top K) / K`

**What it means:** Out of the K chunks shown, what fraction are actually relevant?

- High recall + low precision = the system returns everything including noise.
- High precision + low recall = the system is conservative, might miss answers.

**Why it matters:** You don't want to waste tokens on irrelevant context.

### NDCG@K (Normalized Discounted Cumulative Gain)

**Formula (conceptual):**

1. Assign gain: 2^(relevance) - 1 (so relevance 2 → gain 3, relevance 1 → gain 1, relevance 0 → gain 0)
2. Discount by position: gain / log2(rank + 1) (earlier positions weighted more)
3. DCG = sum of discounted gains at positions 1..K
4. IDCG = DCG of the ideal ranking (all highly relevant chunks first)
5. NDCG = DCG / IDCG

**What it means:** Measures ranking quality — not just "did you find it?" but "did you put the best ones first?"

**Why it matters:** Two systems might have the same recall@5, but one puts the perfect answer at position 1 and the other at position 5. NDCG catches that.

### MRR (Mean Reciprocal Rank)

**Formula:**
For each query: `RR = 1 / (rank of the first relevant chunk)`
MRR = average of RR across all queries.

**What it means:** How high up is the *first* correct answer?

- MRR = 1.0 → the first result is always correct.
- MRR = 0.5 → on average, the first correct answer is at position 2.

**Why it matters:** A high MRR means clinicians can trust the top result. Low MRR means they'll learn to scroll.

### Hit Rate

**Formula:**
`Hit Rate = (queries with at least 1 relevant chunk in top K) / (total queries)`

**What it means:** Binary — did the system find *anything* useful for this query?

**Why it matters:** A system with 85% recall might still completely fail on 15% of queries. Hit rate exposes those zeros.

### Statistical Rigour for Retrieval

- All metrics are **macro-averaged** (compute per query, then average) to avoid one easy query dominating.
- Use **bootstrap resampling** (1,000 iterations) to compute 95% confidence intervals. This says: "If we repeated this experiment on similar data, the true recall would fall in this range 95% of the time."
- Publish the **per-query breakdown table** — no hiding behind averages. A CTO can see exactly which queries failed.

---

## 2. Extraction Metrics (GraphRAG Output vs. Golden Entities/Relations)

You have a golden file with N entities and M relationships. Your system extracted P entities and Q relationships.

### Entity Precision, Recall, F1

- **True Positives (TP):** Extracted entities that exactly match (name + type) a golden entity.
- **False Positives (FP):** Extracted entities not in the golden set.
- **False Negatives (FN):** Golden entities missed by the system.

**Formulas:**
`Precision = TP / (TP + FP)` — How many extracted entities are correct?
`Recall = TP / (TP + FN)` — How many golden entities did you find?
`F1 = 2 * (Precision * Recall) / (Precision + Recall)` — Harmonic mean, balances both.

### Relation Precision, Recall, F1

Same logic, but the match requires (source, target, type) all identical.

**Why F1 matters here:**

- High precision + low recall = the system is conservative (only extracts when confident).
- Low precision + high recall = the system extracts everything but invents fake relations.

### Statistical Rigour for Extraction

- Since we have a single document, we pool all entities/relations and compute **micro-averaged** metrics.
- Per-chunk breakdown shows where extraction fails (e.g., Chunk 12 always misses entities) — actionable debugging.

---

## 3. Inference Metrics (LM Studio / LMQL Logs)

For each query, you have timestamps: when the request was sent, when the first token arrived, when generation finished.

### TTFT (Time to First Token)

**Formula:** `TTFT = timestamp_first_token - timestamp_request_sent`

**What it means:** How long the user waits before seeing *any* response.

**Why p95/p99 matter:** The average might be 80ms, but if 1% of queries take 2 seconds, that's a terrible user experience. P99 exposes the worst case.

### TPOT (Time per Output Token)

**Formula:** `TPOT = (total generation time - TTFT) / (number of generated tokens)`

**What it means:** After the first token, how fast is the model streaming?

**Why it matters:** A model with low TTFT but high TPOT feels sluggish after the first word.

### Throughput (tokens/second)

**Formula:** `Throughput = total_tokens / total_time`

**What it means:** Overall generation speed.

### Failures

Count of requests that timed out, returned errors, or produced invalid JSON. Report as 0/N or X/N with explanation.

### Statistical Rigour for Inference

- Run the same 20 queries **3 times**. If results are deterministic (identical), state that. If there's variance, report mean ± std dev.
- Capture metrics at the server level (LM Studio logs) rather than client-side to avoid network noise.

---

## 4. Provenance: Why It Matters

Every metric is meaningless without knowing **what generated it**. Your manifest captures:

- git commit → exact code version.
- config hashes → exact settings (temperature, max_tokens, embedding model).
- model names → exact LLM and embedding model used.
- data hashes → exact PDF and chunk files.
- run timestamp → when the benchmark was executed.
