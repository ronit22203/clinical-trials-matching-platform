# Retrieval & Query Guide

## Overview

After vectorization, the pipeline supports semantic search and retrieval from the Qdrant vector database. This document covers querying, result interpretation, and integration with downstream applications.

---

## Basic Retrieval

### Python API

```python
from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer

# Initialize
client = QdrantClient("http://localhost:6333")
model = SentenceTransformer("BAAI/bge-small-en-v1.5")

# Query
query_text = "What are the side effects of the medication?"
query_vector = model.encode(query_text).tolist()

# Retrieve
results = client.search(
    collection_name="medical_papers",
    query_vector=query_vector,
    limit=5
)

# Process results
for rank, result in enumerate(results, 1):
    print(f"\n[Rank {rank}] Score: {result.score:.3f}")
    print(f"Source: {result.payload['source']}")
    print(f"Context: {result.payload['context']}")
    print(f"Page: {result.payload['page_number']}")
    print(f"Level: {result.payload['level']}")
```

### REST API

```bash
curl -X POST "http://localhost:6333/collections/medical_papers/points/search" \
  -H "Content-Type: application/json" \
  -d '{
    "vector": [0.1, 0.2, ..., 0.384],
    "limit": 5,
    "with_payload": true
  }'
```

Response structure:
```json
{
  "result": [
    {
      "id": "uuid-string",
      "score": 0.87,
      "payload": {
        "source": "paper_title.md",
        "context": "Methods > Study Design",
        "level": 2,
        "chunk_index": 5,
        "page_number": 3
      }
    }
  ],
  "status": "ok"
}
```

---

## Understanding Search Results

### Relevance Score (0.0 - 1.0)

The score represents cosine similarity between query and result embeddings:

```
Score ≥ 0.80 → Highly relevant (use as-is)
Score 0.70-0.80 → Relevant (likely useful)
Score 0.60-0.70 → Marginally relevant (context dependent)
Score < 0.60 → Likely irrelevant (consider filtering)
```

**Example**:
```
Query: "side effects of aspirin"
  Result 1: "Aspirin can cause headache..." (Score: 0.89) ✓
  Result 2: "Drug interactions with NSAIDs..." (Score: 0.74) ✓
  Result 3: "Pain management strategies..." (Score: 0.55) ✗
```

### Metadata Fields

Each result includes:

| Field | Purpose | Example |
|-------|---------|---------|
| `source` | Original document | `"medical_report.md"` |
| `context` | Hierarchical breadcrumb | `"Clinical Findings > Test Results"` |
| `level` | Header level of context | `2` (##) or `3` (###) |
| `chunk_index` | Position in document | `5` (6th chunk) |
| `page_number` | Source page number (NEW!) | `3` |

Use metadata to:
- **Filter results** by document or section
- **Rank results** by hierarchy level
- **Trace back** to original location
- **Group results** by source

---

## Advanced Querying

### Filtering by Source

```python
results = client.search(
    collection_name="medical_papers",
    query_vector=query_vector,
    limit=5,
    query_filter={
        "must": [
            {
                "key": "source",
                "match": {"value": "medical_report.md"}
            }
        ]
    }
)
```

### Filtering by Context/Section

Find results only from a specific section:

```python
results = client.search(
    collection_name="medical_papers",
    query_vector=query_vector,
    limit=5,
    query_filter={
        "must": [
            {
                "key": "context",
                "match": {"text": "Clinical Findings"}
            }
        ]
    }
)
```

### Filtering by Page Range

Retrieve only from pages 1-5:

```python
results = client.search(
    collection_name="medical_papers",
    query_vector=query_vector,
    limit=5,
    query_filter={
        "must": [
            {
                "key": "page_number",
                "range": {"gte": 1, "lte": 5}
            }
        ]
    }
)
```

### Hybrid Ranking (Score + Metadata)

Re-rank results based on multiple factors:

```python
results = client.search(
    collection_name="medical_papers",
    query_vector=query_vector,
    limit=10  # Retrieve more, then filter
)

# Re-rank: prefer higher level (more important)
results = sorted(
    results,
    key=lambda x: (
        -x.score * 0.7 +  # 70% weight on relevance
        -(x.payload['level'] * 0.3)  # 30% weight on hierarchy
    )
)

# Take top 5
return results[:5]
```

---

## Evaluation & Benchmarking

The pipeline includes an evaluator for measuring retrieval quality.

### Golden Dataset Format

**File**: `benchmarking/golden.json`

```json
{
  "paper": "Sample-filled-in-MR",
  "queries": [
    {
      "id": "Q1",
      "query": "What are the patient demographics?",
      "relevant_chunks": [1, 2, 3]
    },
    {
      "id": "Q2",
      "query": "What tests were performed?",
      "relevant_chunks": [5, 6]
    }
  ],
  "chunks": [
    {
      "chunk_id": 1,
      "page_range": "1-1",
      "content_preview": "Patient demographics section..."
    },
    {
      "chunk_id": 5,
      "page_range": "3-4",
      "content_preview": "Test results section..."
    }
  ]
}
```

### Running Evaluation

```bash
python benchmarking/evaluator.py
```

This:
1. Loads golden dataset
2. Runs queries against Qdrant
3. Computes Recall@5 metric
4. Reports results

Example output:
```
Starting Benchmark: Sample-filled-in-MR
--------------------------------------------------
[HIT]  Q1: What are the patient demographics?...
[HIT]  Q2: What tests were performed?...
[MISS] Q3 | Expected Pages: [5, 6] | Got Pages: [3]
--------------------------------------------------
Successful Hits: 2/3
RECALL@5: 66.67%
Status: ✗ FAILED
```

### Evaluation Metrics

**Recall@K**: Fraction of queries where at least one relevant result appears in top K

```
Recall@5 = (queries with ≥1 relevant result in top 5) / total_queries
```

Example:
- Q1: Top 5 includes relevant result → HIT
- Q2: Top 5 includes relevant result → HIT
- Q3: Top 5 does NOT include relevant result → MISS
- **Recall@5 = 2/3 = 66.67%**

### Improving Performance

**If Recall is low:**

1. **Adjust chunk size** (larger chunks = more context)
   ```yaml
   chunking:
     max_tokens: 1024  # From 512
   ```

2. **Try different embedding model** (larger = more accurate)
   ```yaml
   vectorization:
     model_name: "BAAI/bge-large-en-v1.5"  # 1024 dims
   ```

3. **Hybrid re-ranking** (combine semantic + keyword matching)
   ```python
   # Add keyword boosting for technical terms
   KEYWORD_BOOST = ["MLCube", "DICOM", "HL7"]
   
   # Sort by relevance + keyword presence
   results = sorted(
       results,
       key=lambda x: (
           any(k.lower() in x.payload['content'].lower() 
               for k in KEYWORD_BOOST),
           x.score
       ),
       reverse=True
   )
   ```

4. **Re-process pipeline** (if chunking strategy changed)
   ```bash
   make clean-vectors  # Clear existing embeddings
   make vectorize      # Re-index all chunks
   ```

---

## Integration Patterns

### As a RAG Backend

```python
class MedicalRAG:
    def __init__(self):
        self.client = QdrantClient("http://localhost:6333")
        self.model = SentenceTransformer("BAAI/bge-small-en-v1.5")
    
    def retrieve_context(self, query: str, top_k: int = 5) -> List[str]:
        """Retrieve relevant chunks for a query"""
        query_vector = self.model.encode(query).tolist()
        results = self.client.search(
            collection_name="medical_papers",
            query_vector=query_vector,
            limit=top_k
        )
        
        # Return chunks for LLM context
        return [result.payload.get('content', '') for result in results]
    
    def augment_prompt(self, query: str, llm_model) -> str:
        """Build augmented prompt for LLM"""
        context_chunks = self.retrieve_context(query)
        context = "\n\n".join(context_chunks)
        
        prompt = f"""
Based on the following medical documents:

{context}

Answer this question: {query}
"""
        return prompt
```

### As a Search Engine

```python
from flask import Flask, request, jsonify

app = Flask(__name__)
client = QdrantClient("http://localhost:6333")
model = SentenceTransformer("BAAI/bge-small-en-v1.5")

@app.route('/search', methods=['POST'])
def search():
    data = request.json
    query = data.get('query')
    limit = data.get('limit', 5)
    
    query_vector = model.encode(query).tolist()
    results = client.search(
        collection_name="medical_papers",
        query_vector=query_vector,
        limit=limit
    )
    
    return jsonify({
        "query": query,
        "results": [
            {
                "score": result.score,
                "source": result.payload['source'],
                "context": result.payload['context'],
                "page": result.payload['page_number']
            }
            for result in results
        ]
    })

if __name__ == '__main__':
    app.run(port=5000)
```

### As a Document Q&A System

```python
def answer_question(question: str, llm_client) -> str:
    """Answer a question using retrieved context"""
    
    # 1. Retrieve relevant chunks
    query_vector = model.encode(question).tolist()
    results = client.search(
        collection_name="medical_papers",
        query_vector=query_vector,
        limit=3
    )
    
    # 2. Build context
    sources = [f"{r.payload['source']} (p.{r.payload['page_number']})" 
               for r in results]
    context = "\n".join([r.payload.get('content', '') for r in results])
    
    # 3. Generate answer with LLM
    prompt = f"""
Context from medical documents:
{context}

Question: {question}

Answer based only on the provided context. Include page references.
"""
    
    answer = llm_client.create_completion(prompt)
    
    # 4. Add citations
    answer_with_sources = f"{answer}\n\nSources: {', '.join(sources)}"
    
    return answer_with_sources
```

---

## Troubleshooting Retrieval

**Issue**: All results have low scores (< 0.60)
- **Cause**: Query and documents are semantically distant
- **Solution**: Rephrase query to match document language; check if documents are indexed

**Issue**: Same document returned multiple times
- **Cause**: High redundancy in chunking
- **Solution**: Deduplicate results; consider deduplication_radius in Qdrant

**Issue**: Results are off-topic
- **Cause**: Wrong embedding model or chunking strategy
- **Solution**: Try different embedding model; visualize chunks to verify quality

**Issue**: Slow query latency (> 500ms)
- **Cause**: Large collection or network latency
- **Solution**: Optimize batch size; ensure local Qdrant instance; use indexing

---

## Performance Tuning

### Query Optimization

**Batch queries for efficiency**:
```python
queries = [
    "What are side effects?",
    "What is the dosage?",
    "What are contraindications?"
]

encoded = model.encode(queries)

for i, query_vector in enumerate(encoded):
    results = client.search(
        collection_name="medical_papers",
        query_vector=query_vector,
        limit=5
    )
```

**Use vector caching for repeated queries**:
```python
from functools import lru_cache

@lru_cache(maxsize=1000)
def get_embedding(text: str):
    return tuple(model.encode(text).tolist())
```

---

## See Also

- [Data Flow Guide](data_flow.md) - How data moves through pipeline
- [Processor Guide](processor.md) - Chunking strategy details
- [Storage Guide](storage.md) - Qdrant configuration and management
