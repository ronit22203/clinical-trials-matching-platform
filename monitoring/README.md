# Platform monitoring

Unified Prometheus + Pushgateway + Grafana stack for OCR, embeddings, Qdrant,
Neo4j, and LLM telemetry.

## Quick start

```bash
# from repo root
make monitoring-up

# open dashboards
open http://localhost:3000   # admin / admin
open http://localhost:9090   # Prometheus targets
```

Stop with `make monitoring-down`.

## Ports

| Service      | Port | Notes                                      |
|--------------|------|--------------------------------------------|
| Grafana      | 3000 | admin / admin                              |
| Prometheus   | 9090 | scrapes apps, Qdrant, pushgateway          |
| Pushgateway  | 9091 | LLM benchmark gauges (`--prometheus`)      |

## Scrape targets

Prometheus reaches host processes via `host.docker.internal`:

| Job         | Target                              |
|-------------|-------------------------------------|
| pushgateway | `pushgateway:9091`                  |
| qdrant      | `host.docker.internal:6333/metrics` |
| ingestion   | `host.docker.internal:8002/metrics` |
| reasoning   | `host.docker.internal:8000/metrics` |

Neo4j Community has no Prometheus exporter; graph latency is scraped from the
reasoning API (`neo4j_query_duration_seconds`).

Start Qdrant/Neo4j (`docker compose -f docker-compose.local.yml up -d`) and the
ingestion/reasoning APIs so those targets stay healthy.

## App metrics

- **Ingestion** (`:8002`): OCR duration/pages/confidence, embed encode, Qdrant upserts
- **Reasoning** (`:8000`): LLM request latency/tokens, embed/rerank, Qdrant/Neo4j queries
- **Benchmarks only**: push to Pushgateway (`localhost:9091`) via `--prometheus`

OCR / embed / Qdrant / Neo4j / live LLM metrics are **scraped** from the APIs.
An empty Pushgateway UI is normal until you run an inference benchmark with
`--prometheus`.

Verify scrapes in Prometheus → Status → Targets, or query e.g. `ocr_pages_total`.

## Dashboards

Provisioned under Grafana → Dashboards:

- OCR, Embeddings, Qdrant, Neo4j, Language Model
- Ollama Benchmark (legacy pushgateway panels)

## Migration note

The previous stack under `core-llm-inference/monitoring/` is superseded by this
directory. Pushgateway URL (`http://localhost:9091`) is unchanged.
