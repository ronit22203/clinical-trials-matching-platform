# Infrastructure Reference

> For design rationale behind these decisions, see [DESIGN.md](DESIGN.md).  
> For cloud provider setup steps, see [docs/SETTING_UP_CLOUD_DATABASES.md](docs/SETTING_UP_CLOUD_DATABASES.md).

---

## Topology Overview

```
┌──────────────────────────────────────────────────────────────────┐
│  PRIMARY COMPUTE  (90% of traffic)                               │
│  g4dn.xlarge / g4dn.vt (EC2 Spot)                               │
│  Surya OCR + BAAI/bge-small-en-v1.5 embeddings                  │
│  Cost: $0.10–0.15/hr · Runtime: few hours/week · Terminates     │
└──────────────────────────────────────────────────────────────────┘
         │ spot termination or complex document
         ▼
┌──────────────────────────────────────────────────────────────────┐
│  FALLBACK TIER 1  (8% of traffic)                                │
│  Azure Document Intelligence                                     │
│  API-based OCR, no infrastructure to manage                      │
│  Cost: $1.50/1,000 pages · Budget cap enforced via circuit       │
│  breaker (config/circuit_breaker.yml)                            │
└──────────────────────────────────────────────────────────────────┘
         │ budget cap hit or Azure endpoint unreachable
         ▼
┌──────────────────────────────────────────────────────────────────┐
│  FALLBACK TIER 2  (2% of traffic)                                │
│  CPU Tesseract (local)                                           │
│  Cost: ~$0.01/hr · Quality: degraded (Recall@5 = 0.76)          │
│  Documents processed here are flagged for reprocessing           │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│  ALWAYS-ON CORE  (24/7)                                          │
│  t4g.small — $12/month                                          │
│  Qdrant (port 6333/6334)  ·  Neo4j (port 7474/7687)             │
│  All workers write here; all queries are served from here        │
└──────────────────────────────────────────────────────────────────┘
```

---

## Cost Profile

| Component | Instance Type | Runtime | Hourly Cost | Monthly Cost | Traffic Share |
|-----------|---------------|---------|-------------|--------------|---------------|
| Primary GPU | g4dn.xlarge (spot) | Few hours/week | $0.10–0.15 | ~$2–4 | 90% |
| Persistent DB | t4g.small | 24/7 | $0.0084 | $12.00 | — |
| Fallback OCR | Azure Document Intelligence | On-demand | $1.50/1k pages | Variable | 8% |
| Fallback CPU | Tesseract | Rare | $0.01/hr | <$0.50 | 2% |

**Monthly baseline: ~$14–16 + variable Azure DI costs.**  
**Cost per document: ~$0.00012 average** (weighted across tiers).  
**Spot vs. on-demand saving: 93%.**

---

## Fallback Trigger Matrix

| Trigger | Frequency | Transition | Measured Recovery Time |
|---------|-----------|------------|------------------------|
| Spot termination | 3–5% of jobs | GPU → Azure DI | 45s (p50) |
| Complex document (OCR-heavy) | ~2% | GPU → Azure DI | Immediate (API-based) |
| Document >50 pages | ~1% | GPU → CPU Tesseract | 2.3× slower than GPU |
| Azure DI budget cap reached | Configurable | Azure DI → CPU | Depends on poll interval (60s) |
| Both clouds unreachable | <0.1% | Any → CPU | Depends on outage duration |

Detection time: **30 seconds** (health check interval).  
The "both clouds down" scenario results in a 10× latency increase with 100% cost reduction. Recovery is automatic when either cloud becomes reachable.

---

## Cost per Processing Path

| Path | $/1,000 pages | Typical use case |
|------|---------------|-----------------|
| GPU spot | $0.08–0.12 | Normal operations |
| Azure Document Intelligence | $1.50 | Spot terminated or complex layout |
| CPU Tesseract | $0.001 | Both clouds degraded |
| GPU on-demand (no spot) | $0.50–0.80 | Spot capacity unavailable in AZ |

---

## Persistent Tier Utilisation

The `t4g.small` hosts both Qdrant and Neo4j. Current utilisation measured during peak batch ingestion:

| Database | Storage Used | RAM Usage | CPU Usage | Peak Connections |
|----------|-------------|-----------|-----------|-----------------|
| Qdrant | 12 GB | 1.2 GB | 5–10% | 0–5 (batch writes) |
| Neo4j | 8 GB | 1.8 GB | 2–8% | 0–3 |
| **Total** | **20 GB** | **3.0 GB / 4 GB** | **<15%** | — |

**Headroom:** 25% RAM, 85% CPU. The current instance can handle approximately 5× the current load before requiring an upgrade to `t4g.medium`.

---

## Operational Capabilities

1. **Cost-to-serve per document:** $0.00012 average across all tiers.
2. **Uptime SLA:** 99.9% — both clouds failing simultaneously represents the 0.1% tail.
3. **Budget exhaustion protection:** Hard cap on Azure DI spend enforced by `src/circuit_breaker.py`; auto-fallback to CPU Tesseract when the cap is reached.
4. **Spot volatility hedge:** Azure DI absorbs termination spikes without manual intervention.

---

## Infrastructure as Code

The Azure fallback storage account can be reprovisioned from the ARM template stored in this repository:

```bash
az deployment group create \
    --resource-group clinical-trials-pdfs-prod-fallback \
    --template-file infra/azure/fallback-storage.json
```

See [docs/SETTING_UP_CLOUD_DATABASES.md](docs/SETTING_UP_CLOUD_DATABASES.md) for the full setup procedure, including S3 bucket creation and config file updates.
