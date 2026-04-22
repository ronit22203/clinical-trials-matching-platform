import logging
from qdrant_client import QdrantClient
from src.storage.embedder import MedicalVectorizer

# Setup
vectorizer = MedicalVectorizer()
COLLECTION = vectorizer.collection_name

# The Query (Simulating a Doctor asking)
query_text = "Does the patient have dementia?"

print(f"Querying: '{query_text}'...")

# 1. Embed Query
query_vector = vectorizer.embedding_model.encode(query_text).tolist()

# 2. Search Qdrant
results = vectorizer.client.query_points(
    collection_name=COLLECTION,
    query=query_vector,
    limit=3
)

# 3. Display Results
print("\n--- Retrieval Results ---")
for i, hit in enumerate(results.points):
    print(f"\n[Rank {i+1}] Score: {hit.score:.4f}")
    print(f"Source: {hit.payload.get('context', 'Unknown')}")
    print(f"Content Preview: {hit.payload.get('source', 'Unknown')}")
