# Storage and Vectorization Stage Documentation

## Overview

The storage stage handles embedding generation, Qdrant vector database management, and retrieval infrastructure. This stage consists of two components:

1. **MedicalVectorizer** - Embeddings and indexing
2. **QdrantManager** - Collection management and administration

## MedicalVectorizer

Located in `src/storage/embedder.py`, this class orchestrates the full vectorization pipeline.

### Pipeline Architecture

```
Markdown Files (data/interim/)
    |
    v
[Load & Clean]
    - TextCleaner removes artifacts
    |
    v
[Chunk]
    - MarkdownChunker creates context-aware chunks
    |
    v
[Embed]
    - SentenceTransformer generates embeddings
    |
    v
[Index]
    - Upsert to Qdrant with metadata
    |
    v
Searchable Vector Database
```

### Usage

```python
from src.storage.embedder import MedicalVectorizer, ConfigLoader

# Initialize vectorizer
config = ConfigLoader.load()
vectorizer = MedicalVectorizer(config=config)

# Process all markdown files in a directory
vectorizer.run("data/interim")

# Or process a single file
vectorizer.process_file("data/interim/paper.md")
```

### CLI Usage

```bash
# Run from project root
python src/storage/embedder.py

# With custom input directory
python src/storage/embedder.py -i /custom/path

# With custom config
python src/storage/embedder.py -c /custom/config.yaml

# Via Makefile
make vectorize
```

### Configuration

From `config/settings.yaml`:

```yaml
vectorization:
  input_dir: "data/interim"              # Where to read markdown files
  qdrant_url: "http://localhost:6333"    # Qdrant server address
  collection_name: "medical_papers"      # Collection name in Qdrant
  model_name: "BAAI/bge-small-en-v1.5"   # Embedding model
  chunk_size: 1500                       # Max tokens per chunk
  chunk_overlap: 300                     # Paragraph overlap (not used)
  batch_size: 64                         # Batch size for upserting
```

### Embedding Model

The pipeline uses **BAAI/bge-small-en-v1.5** by default:

- Model type: Dense passage retrieval
- Embedding dimension: 384
- Supported languages: English, Chinese, others
- Size: 91MB (fast, suitable for CPU inference)
- Performance: High quality for RAG

Alternative models:

```yaml
# Larger, more accurate
model_name: "BAAI/bge-large-en-v1.5"     # 1.3GB, 1024 dims

# Multilingual
model_name: "BAAI/bge-m3"                # 2.3GB, 1024 dims, 110+ languages

# Lightweight
model_name: "sentence-transformers/all-MiniLM-L6-v2"  # 22MB, 384 dims
```

### Process Flow

#### Step 1: Load Configuration

```python
config = ConfigLoader.load("config/settings.yaml")
```

Parses YAML configuration and provides validated settings.

#### Step 2: Initialize Components

```python
self.embedding_model = SentenceTransformer(model_name)
self.embedding_dim = self.embedding_model.get_sentence_embedding_dimension()
self.cleaner = TextCleaner()
self.chunker = MarkdownChunker(max_tokens=chunk_size)
```

Loads embedding model, initializes cleaner and chunker.

#### Step 3: Create Qdrant Collection

```python
self.client.create_collection(
    collection_name=collection_name,
    vectors_config=VectorParams(size=embedding_dim, distance=Distance.COSINE)
)
```

Creates vector collection with COSINE distance metric (ideal for sentence embeddings).

#### Step 4: Process Files

For each markdown file:

1. Load file
2. Clean with TextCleaner
3. Chunk with MarkdownChunker
4. Generate embeddings
5. Prepare Qdrant points with metadata
6. Batch upsert to Qdrant

### Output Data Structure

Qdrant points stored with structure:

```python
{
    "id": "uuid-string",
    "vector": [0.123, -0.456, ...],  # 384-dim embedding
    "payload": {
        "source": "paper_title.md",
        "context": "Methods > Study Design",
        "level": 2,
        "chunk_index": 5,
        "page_number": 3  # NEW: Source page number
    }
}
```

**Payload Fields**:

| Field | Type | Purpose | Example |
|-------|------|---------|---------|
| `source` | string | Original document filename | `"medical_report.md"` |
| `context` | string | Hierarchical breadcrumb path | `"Clinical Findings > Test Results"` |
| `level` | int | Header level (1-4) | `2` (##) |
| `chunk_index` | int | Position of chunk in document | `5` |
| `page_number` | int | Source page number (from PDF) | `3` |

**Metadata enables**:
- Filter results by source document
- Understand semantic context
- Rank results by header hierarchy
- Trace back to original page number
- Evaluate retrieval quality against ground truth

### Error Handling

```python
try:
    vectorizer = MedicalVectorizer()
    vectorizer.run()
except FileNotFoundError:
    print("Markdown files not found in data/interim/")
except ConnectionError:
    print("Cannot connect to Qdrant. Is it running? (make docker-up)")
except Exception as e:
    print(f"Embedding failed: {e}")
```

### Performance Optimization

**GPU Acceleration** (Recommended for large datasets):

```bash
# NVIDIA GPUs
pip install torch-cuda

# Apple Silicon (M1/M2)
pip install torch  # Already optimized for MPS
```

Model auto-detects and uses available GPU.

**Batch Processing**:

```yaml
batch_size: 64  # Increase for faster indexing (uses more memory)
```

Typical speeds:
- CPU: 100-200 embeddings/second
- GPU: 1000-5000 embeddings/second

### Testing

```bash
make test-embedder
```

Tests:
- Config loading
- Model initialization
- Qdrant connection
- Sample file processing
- Metadata structure

## QdrantManager

Located in `src/storage/qdrant_client.py`, this class manages Qdrant collections.

### Usage

```python
from src.storage.qdrant_client import QdrantManager

manager = QdrantManager(config_path="config/settings.yaml")

# Operations
manager.list_collections()
manager.get_collection_stats()
manager.delete_collection()
manager.clear_collection()  # Delete all points, keep structure
```

### CLI Operations

```bash
# List all collections
python src/storage/qdrant_client.py list

# Show statistics
python src/storage/qdrant_client.py stats

# Clear all embeddings (interactive)
python src/storage/qdrant_client.py clear

# Delete collection (interactive)
python src/storage/qdrant_client.py delete

# Via Makefile
make qdrant-clear
make qdrant-delete
```

### Collection Statistics

Example output:

```
Collection: medical_papers
  Total points: 1250
  Total vectors: 1250
```

Points and vectors are 1:1 for our use case (one embedding per chunk).

### Configuration Path Resolution

The manager resolves config paths as:

1. Explicit path: `QdrantManager(config_path="/custom/path")`
2. Default: `config/settings.yaml` in project root

### Qdrant Data Structure

```
Qdrant Instance (http://localhost:6333)
    |
    ├── Collection: medical_papers
    │   ├── Vector dimension: 384
    │   ├── Distance metric: COSINE
    │   ├── Points: 1250
    │   └── Payload schema:
    │       ├── source (string)
    │       ├── context (string)
    │       ├── level (integer)
    │       └── chunk_index (integer)
    │
    └── Collection: other_papers (optional)
```

### Docker Management

Start Qdrant:

```bash
make docker-up

# Or directly
docker-compose -f infra/docker-compose.yaml up -d
```

The service will:
- Start Qdrant on `http://localhost:6333`
- Mount persistent storage to Docker volume
- Enable REST API on port 6333
- Enable gRPC on port 6334

Stop and cleanup:

```bash
make docker-down
# Or: docker-compose -f infra/docker-compose.yaml down
```

View logs:

```bash
make docker-logs
# Or: docker-compose -f infra/docker-compose.yaml logs -f
```

### Querying Qdrant

Direct Python query:

```python
from qdrant_client import QdrantClient

client = QdrantClient("http://localhost:6333")

# Search for similar embeddings
results = client.search(
    collection_name="medical_papers",
    query_vector=query_embedding,
    limit=5
)

# Results
for result in results:
    print(f"Score: {result.score}")
    print(f"Context: {result.payload['context']}")
    print(f"Source: {result.payload['source']}")
```

Using REST API:

```bash
curl -X POST "http://localhost:6333/collections/medical_papers/points/search" \
  -H "Content-Type: application/json" \
  -d '{
    "vector": [0.1, 0.2, ..., 0.384],
    "limit": 5
  }'
```

### Troubleshooting

**Issue: "Connection refused"**

```bash
# Check if Qdrant is running
docker ps | grep qdrant

# Start if not running
make docker-up
```

**Issue: "Collection does not exist"**

```bash
# List collections
python src/storage/qdrant_client.py list

# Verify vectorization completed
make test-embedder
```

**Issue: "Out of memory during vectorization"**

Reduce batch size:

```yaml
vectorization:
  batch_size: 32  # From 64
```

Or use smaller model:

```yaml
model_name: "sentence-transformers/all-MiniLM-L6-v2"
```

**Issue: Slow embedding generation**

Ensure GPU is being used:

```python
# Check in vectorizer logs
# "Loading embedding model: BAAI/bge-small-en-v1.5"
# Should be on GPU if available
```

## Full Pipeline Integration

```
Stage 1: Extraction
    PDF -> PDFMarkerExtractor -> Markdown
    
Stage 2: Processing
    Markdown -> TextCleaner -> Cleaned Markdown
    Cleaned Markdown -> MarkdownChunker -> Chunks with Context
    
Stage 3: Vectorization (This Stage)
    Chunks -> SentenceTransformer -> Embeddings
    Embeddings -> QdrantManager -> Indexed Vector Database
    
Retrieval
    Query -> Embed -> Search Qdrant -> Get Relevant Chunks
```

## Performance Benchmarks

Processing 50-page medical paper:

- Extraction: 20 seconds
- Cleaning: 2 seconds
- Chunking: 1 second
- Embedding (CPU): 30 seconds
- Qdrant indexing: 2 seconds
- **Total: ~55 seconds**

Retrieval latency:
- Query embedding: 50-100ms
- Qdrant search: 10-50ms
- **Total: ~100-150ms**

Memory requirements:
- Embedding model: 200MB (BAAI/bge-small-en-v1.5)
- Qdrant instance: 500MB-2GB (depends on data)
- Working memory: 1-2GB
- **Total: 2-4GB recommended**

## Advanced Configuration

### Custom Embedding Model

```python
from sentence_transformers import SentenceTransformer

# In embedder.py, modify initialization
model = SentenceTransformer("custom-model-name")
embedding_dim = model.get_sentence_embedding_dimension()
```

### Custom Distance Metric

Default is COSINE (recommended for embeddings). Alternatives:

```python
from qdrant_client.models import Distance

Distance.COSINE      # Recommended for sentence embeddings
Distance.EUCLIDEAN   # For absolute distances
Distance.DOT         # For dot product similarity
Distance.MANHATTAN   # For L1 distance
```

Modify in collection creation:

```python
vectors_config=VectorParams(size=embedding_dim, distance=Distance.DOT)
```

### Persistence Configuration

Edit `infra/docker-compose.yaml`:

```yaml
services:
  qdrant:
    volumes:
      - qdrant_data_vol:/qdrant/storage  # Named volume
      # Or absolute path:
      # - /absolute/path/to/qdrant:/qdrant/storage
```

## Monitoring and Maintenance

Health check:

```bash
curl http://localhost:6333/readyz
# Returns 200 if healthy
```

Collection maintenance:

```bash
# Compact collection (remove deleted points)
python -c "from qdrant_client import QdrantClient; \
  c = QdrantClient('http://localhost:6333'); \
  c.recreate_collection('medical_papers')"

# Backup collection
python -c "from qdrant_client import QdrantClient; \
  c = QdrantClient('http://localhost:6333'); \
  # Use snapshot functionality
```

## Security Notes

For production:

1. Enable authentication in Qdrant
2. Use HTTPS/TLS for connections
3. Restrict network access to Qdrant port 6333
4. Use read-only credentials for retrieval
5. Enable audit logging

See Qdrant documentation for production deployment.
