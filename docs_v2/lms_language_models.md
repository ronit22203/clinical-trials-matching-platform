
# LM Studio Language Model Selection

## Strategy: One Model, Two Use Cases

The platform requires two distinct inference capabilities:

| Use Case | Requirement | Model Type |
| :--- | :--- | :--- |
| **Entity-Relation Extraction (NER)** | Precision, BioBERT-level accuracy, structured output | Encoder or fine-tuned decoder |
| **Agent Language Model** | Reasoning, tool calling, conversation, instruction following | General-purpose instruct/chat model |

A single model can serve both roles, but combining them introduces trade-offs: general chat models sacrifice NER precision, while pure NER models lack the reasoning capacity required for agentic workflows.

---

## Architecture Decision

The platform (`clinical-graphrag-agents`) separates these concerns into distinct components:

- `entity_extractor.py` uses **BioBERT** for NER
- The agent layer uses a general-purpose LLM for reasoning and tool orchestration

This separation is intentional. The LLM acts as the **agent brain** responsible for:

- Interpreting clinical queries
- Selecting tools (`pubmed_search`, `fda_adverse_events`, `graphrag_search`)
- Synthesising responses from retrieved data
- Following the YAML-defined system prompt

---

## Model Selection

| Model | Verdict | Rationale |
| :--- | :--- | :--- |
| **BioMistral-Clinical-7B** | ✅ **Recommended** | Mistral-based, clinical fine-tune, strong reasoning and domain knowledge |
| **Medical-Llama3-8B** | ✅ Solid alternative | Llama 3 architecture, medical fine-tune, strong instruction following |
| **phi-3-clinical** | ⚠️ Smaller (3.8B) | Faster and lower VRAM, but reduced reasoning depth |
| **ClinicalGPT-*** | ⚠️ Older base | May lack instruction tuning for agentic tool-calling workflows |

---

## Installation

```bash
# Download the recommended model
lms get MaziyarPanahi/BioMistral-Clinical-7B-GGUF

# Alternative: Llama 3 base
lms get ruslanmv/Medical-Llama3-8B-GGUF
```

---

## Agent Configuration

**`config/app.yaml` — agent model reference:**

```yaml
name: "Clinical Research Assistant"
model: openai/BioMistral-Clinical-7B  # or Medical-Llama3-8B
system_prompt: |
  A clinical research assistant embedded in a regulated healthcare platform.
  Access to tools: PubMed search, openFDA adverse events, ClinicalTrials.gov, and GraphRAG.
  Always cite sources. Flag uncertainty. Do not hallucinate.
tools:
  - pubmed_search
  - fda_adverse_events
  - clinical_trials
  - graphrag_search
```

**NER remains separate:**  
`entity_extractor.py` continues using `samrawal/bert-base-uncased_clinical-ner` (BioBERT). This is the correct tool for strict structured entity extraction.

---

## Quantization Reference

When downloading a model in LM Studio, the quantization format controls the trade-off between quality and memory footprint:

| Format | Quality | Size vs FP16 | Recommended For |
| :--- | :--- | :--- | :--- |
| **FP16** | Original, lossless | 100% | Production servers with ample VRAM |
| **Q8_0** | Near-lossless | ~50% | High-quality inference, capable GPU |
| **Q6_K** | Excellent | ~40% | Balanced quality/size |
| **Q5_K_M / Q5_K_S** | Very good | ~35% | **Sweet spot** for local development |
| **Q4_K_M** | Good | ~25% | Limited VRAM, maximum throughput |

K-quants (`Q5_K_S`, `Q6_K`) are modern GGUF formats that preserve more accuracy per byte than earlier quantization schemes.

### Hardware guidance

| Hardware | Recommended format |
| :--- | :--- |
| Apple Silicon M4 (12–16 GB unified memory) | **Q5_K_S** — 5.00 GB, fits comfortably, leaves headroom for KV cache |
| NVIDIA RTX 5080 (16 GB VRAM) | **Q8_0** or **FP16** for maximum fidelity |

---

## Server Startup

```bash
# Load the model
lms load BioMistral-Clinical-7B

# Start the OpenAI-compatible inference server
lms server start

# Verify the server is serving the model
curl http://localhost:1234/v1/models
```

Update `config/app.yaml` to point the agent at the local server:

```yaml
model: openai/BioMistral-Clinical-7B
model_params:
  api_base: http://localhost:1234/v1
  temperature: 0.1
```

The platform's tool-calling and audit trail pipeline requires no changes when switching models — the model identifier is the only configuration variable.
