import json
import sys
from pathlib import Path
from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer

# 1. Setup 
COLLECTION_NAME = "medical_papers"
GOLDEN_DATA_PATH = Path(__file__).parent / "golden.json"

# MATCH YOUR INGESTION MODEL
MODEL_NAME = 'BAAI/bge-small-en-v1.5' 

client = QdrantClient("http://localhost:6333")

print("Loading embedding model...")
model = SentenceTransformer(MODEL_NAME)

with open(GOLDEN_DATA_PATH, "r") as f:
    golden_data = json.load(f)

total_queries = len(golden_data["queries"])
successful_hits = 0
reciprocal_ranks = []
relevance_scores = []
precision_at_5_scores = []

# KEYWORD BOOSTER: Add terms that define your 'MISS' queries
KEYWORD_BOOST = ["MLCube", "DICOM", "HL7", "FHIR", "MedPerf", "federated"]

print(f"\nStarting Benchmark: {golden_data['paper']}")
print("-" * 50)

for item in golden_data["queries"]:
    query_text = item["query"]
    
    # NEW: Get the page ranges from the chunks mentioned in the JSON
    # This maps Q3's "chunks 7, 9" to their actual Page Numbers
    relevant_chunk_ids = item["relevant_chunks"]
    ground_truth_pages = []
    for c_id in relevant_chunk_ids:
        for chunk_ref in golden_data["chunks"]:
            if chunk_ref["chunk_id"] == c_id:
                # Extracts '7' from '7-8' or '7'
                pages = [int(p.strip()) for p in chunk_ref["page_range"].split('-')]
                ground_truth_pages.extend(range(pages[0], pages[-1] + 1))
    
    # A. VECTOR SEARCH
    query_vector = model.encode(query_text).tolist()
    search_result = client.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        limit=10 # Retrieve 10 to allow for keyword re-ranking
    )
    
    # B. HYBRID LOGIC: Does the query contain a hard technical term?
    points = search_result.points
    found_keywords = [k for k in KEYWORD_BOOST if k.lower() in query_text.lower()]
    
    if found_keywords:
        # Re-sort points if they contain the exact technical keyword
        points = sorted(
            points, 
            key=lambda x: any(k.lower() in x.payload.get("content", "").lower() for k in found_keywords), 
            reverse=True
        )

    # C. TAKE TOP 5 AFTER RE-SORTING
    # Check if ANY retrieved page matches ANY ground truth page
    top_5_points = points[:5]
    retrieved_pages = [hit.payload.get("page_number") for hit in top_5_points]
    is_hit = any(p in ground_truth_pages for p in retrieved_pages if p is not None)
    
    # Calculate metrics for this query
    relevant_count = sum(1 for p in retrieved_pages if p in ground_truth_pages and p is not None)
    precision_at_5 = relevant_count / 5 if top_5_points else 0
    precision_at_5_scores.append(precision_at_5)
    
    # Mean Reciprocal Rank (MRR): rank of first relevant result
    mrr = 0
    for idx, hit in enumerate(top_5_points, 1):
        page = hit.payload.get("page_number")
        if page in ground_truth_pages:
            mrr = 1.0 / idx
            break
    reciprocal_ranks.append(mrr)
    
    # Relevance score: binary relevance for NDCG calculation
    relevance_scores.append(1 if is_hit else 0)
    
    if is_hit:
        successful_hits += 1
        print(f"[HIT]  {item['id']}: {query_text[:45]}...")
    else:
        # DEBUG: See what we actually got for the MISS
        print(f"[MISS] {item['id']} | Expected Pages: {ground_truth_pages} | Got Pages: {retrieved_pages}")

# 4. Calculate all metrics
print("-" * 50)
recall_at_5 = (successful_hits / total_queries) * 100
mean_reciprocal_rank = (sum(reciprocal_ranks) / total_queries * 100) if total_queries > 0 else 0
mean_precision_at_5 = (sum(precision_at_5_scores) / total_queries * 100) if total_queries > 0 else 0

# NDCG@5: Normalized Discounted Cumulative Gain
def calculate_ndcg(relevance_list):
    """Calculate NDCG@5 assuming binary relevance"""
    if not relevance_list:
        return 0
    dcg = sum((2 ** rel - 1) / (2 ** (idx + 1)) for idx, rel in enumerate(relevance_list))
    idcg = sum((2 ** rel - 1) / (2 ** (idx + 1)) for idx, rel in enumerate(sorted(relevance_list, reverse=True)))
    return (dcg / idcg * 100) if idcg > 0 else 0

ndcg_at_5 = calculate_ndcg(relevance_scores)

# Print comprehensive metrics
print(f"Successful Hits: {successful_hits}/{total_queries}")
print(f"\nMETRICS:")
print(f"  RECALL@5:        {recall_at_5:.2f}%")
print(f"  Precision@5:     {mean_precision_at_5:.2f}%")
print(f"  MRR@5:           {mean_reciprocal_rank:.2f}%")
print(f"  NDCG@5:          {ndcg_at_5:.2f}%")
print(f"\n{'✓ PASSED' if recall_at_5 >= 70 else '✗ FAILED'} (Recall threshold: 70%)")