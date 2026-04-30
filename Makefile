SHELL := /bin/bash

# --- [ Colors ] ---------------------------------------------------------------
BLUE   := \033[34m
CYAN   := \033[36m
GREEN  := \033[32m
YELLOW := \033[33m
RED    := \033[31m
BOLD   := \033[1m
NC     := \033[0m

REASONING_DIR := agentic-reasoning
ACQUISITION_DIR := data-acquisition
INGESTION_DIR := data-ingestion
UI_DIR := platform-ui
BENCHMARKING_DIR := benchmarking
CONFIG_FILE := config/app.yaml

REASONING_PYTHON := .venv/bin/python
ACQUISITION_PYTHON := .venv/bin/python
UI_PACKAGE_MANAGER ?= npm

SOURCE ?= medrxiv
MAX_PDFS ?= 2
N ?= 2
QUERY ?= What is the latest evidence for adjuvant immunotherapy in melanoma?
SEARCH_QUERY ?= cancer immunotherapy
RECORD_ID ?=
PDF_TYPE ?= paper
AGENT ?= local_assistant
SGLANG_AGENT ?= sglang_assistant
SKIP ?=
DOC ?=
EXEC1 ?=
EXEC2 ?=

# --- [ Benchmark config ] -----------------------------------------------------
BENCH_PYTHON   ?= $(CURDIR)/$(REASONING_DIR)/.venv/bin/python
BENCH_RUNS     ?= 3
RUN_DATE       := $(shell date +%Y%m%d_%H%M%S)
RUN_HASH       := $(shell git rev-parse --short HEAD 2>/dev/null || echo unknown)
RUN_DIR        ?= $(BENCHMARKING_DIR)/results/run_$(RUN_DATE)_$(RUN_HASH)

# Reranker config (defaults to BGE base; override with RERANKER_MODEL="" to disable)
RERANKER_MODEL ?= BAAI/bge-reranker-base
RETRIEVAL_K    ?=

_RERANKER_ARGS := $(if $(RERANKER_MODEL),--reranker-model "$(RERANKER_MODEL)",) \
                  $(if $(RETRIEVAL_K),--retrieval-k "$(RETRIEVAL_K)",)

# Golden PDF for deterministic end-to-end runs (path relative to repo root)
BENCH_PDF      ?= data/pdfs/raw/medrxiv/2026/04/22/10.64898/2026.03.17.26348414/paper.pdf
BENCH_PDF_DIR  := $(dir $(BENCH_PDF))
DET_RUN_ID     := det_$(RUN_DATE)_$(RUN_HASH)
DET_RUN_DIR    := $(BENCHMARKING_DIR)/results/$(DET_RUN_ID)

FETCHER_SCRIPT = $(if $(filter clinical_trials,$(SOURCE)),clinical_trials_pdf.py,$(SOURCE).py)

.PHONY: help \
	bootstrap validate up down serve serve-api serve-ui fetch ingest \
	status benchmark-sepsis \
	benchmark-all benchmark-retrieval benchmark-extraction benchmark-inference benchmark-report \
	deterministic-run _det-ingest-timed _det-graph-timed _det-finalize \
	clean clean-all clean-artifacts clean-ocr clean-md clean-chunks clean-vectors clean-graph clean-hard \
	ui-install ui-dev ui-build ui-start \
	reasoning-install reasoning-clean reasoning-test reasoning-run reasoning-run-query \
	reasoning-run-temporal reasoning-run-temporal-hitl reasoning-temporal-up reasoning-temporal-down \
	reasoning-temporal-worker reasoning-temporal-run reasoning-temporal-run-hitl \
	reasoning-graphrag-up reasoning-graphrag-down reasoning-services-up reasoning-services-down \
	reasoning-download-models reasoning-sglang-run reasoning-sglang-run-query \
	reasoning-sglang-run-temporal reasoning-sglang-run-temporal-hitl \
	reasoning-temporal-run-sglang reasoning-temporal-run-hitl-sglang reasoning-serve-api \
	simple-ui-serve \
	acquisition-install acquisition-test acquisition-fetch acquisition-source-validate \
	acquisition-source-search acquisition-source-fetch \
	ingestion-install ingestion-test ingestion-test-processors ingestion-test-embedder \
	ingestion-test-qdrant ingestion-run ingestion-inspect ingestion-qdrant-up \
	ingestion-qdrant-down ingestion-qdrant-logs ingestion-qdrant-clear ingestion-qdrant-delete \
	ingestion-neo4j-build ingestion-neo4j-delete ingestion-neo4j-stats \
	ingestion-list-documents ingestion-list-executions ingestion-compare-runs \
	ingestion-clean ingestion-clean-all

help: ## Show all root orchestration targets
	@printf "\n$(BOLD)Healthcare Platform — Unified Control Surface$(NC)\n\n"
	@grep -E '^[a-zA-Z0-9_.-]+:.*?## ' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  $(CYAN)%-34s$(NC) %s\n", $$1, $$2}'
	@printf "\n"

status: ## Show running containers and data artifact counts
	@printf "$(BOLD)--- Infrastructure ---$(NC)\n"
	@docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null | grep -E "qdrant|neo4j|temporal|postgres" || printf "  $(YELLOW)No platform containers running$(NC)\n"
	@printf "\n$(BOLD)--- Storage Artifacts ---$(NC)\n"
	@printf "  PDFs:   %s\n" "$$(find data/pdfs -type f -name '*.pdf' 2>/dev/null | wc -l | xargs)"
	@printf "  OCR:    %s\n" "$$(find data/artifacts/extract -type f 2>/dev/null | wc -l | xargs)"
	@printf "  Chunks: %s\n" "$$(find data/artifacts/chunk -type f 2>/dev/null | wc -l | xargs)"
	@printf "\n$(BOLD)--- LM Studio ---$(NC)\n"
	@curl -s http://localhost:1234/v1/models 2>/dev/null | python3 -c \
		"import sys, json; m=json.load(sys.stdin); [print('  ' + x['id']) for x in m.get('data',[])]" \
		|| printf "  $(YELLOW)LM Studio not running$(NC)\n"

bootstrap: ## Bootstrap Python and Node dependencies
	@./scripts/bootstrap.sh

validate: ## Check env file, LM Studio, Qdrant, and Neo4j connectivity
	@bash -c 'set -euo pipefail; \
		test -f .env.local || { printf "$(RED)FAIL: missing .env.local$(NC)\n"; exit 1; }; \
		set -a; source .env.local; set +a; \
		LM_STUDIO_URL="$${LM_STUDIO_BASE_URL:-http://localhost:1234/v1}"; \
		QDRANT_ADDR="$${QDRANT_URL:-http://localhost:6333}"; \
		NEO4J_BOLT="$${NEO4J_URI:-bolt://localhost:7687}"; \
		printf "Checking LM Studio at $$LM_STUDIO_URL\n"; \
		curl --fail --silent "$$LM_STUDIO_URL/models" >/dev/null \
			&& printf "  $(GREEN)LM Studio OK$(NC)\n" \
			|| { printf "  $(RED)FAIL: LM Studio not reachable$(NC)\n"; exit 1; }; \
		printf "Checking Qdrant at $$QDRANT_ADDR\n"; \
		curl --fail --silent "$$QDRANT_ADDR/collections" >/dev/null \
			&& printf "  $(GREEN)Qdrant OK$(NC)\n" \
			|| { printf "  $(RED)FAIL: Qdrant not reachable$(NC)\n"; exit 1; }; \
		printf "Checking Neo4j at $$NEO4J_BOLT\n"; \
		NEO4J_HOST=$$(echo "$$NEO4J_BOLT" | sed "s|.*://||" | cut -d: -f1); \
		NEO4J_PORT=$$(echo "$$NEO4J_BOLT" | sed "s|.*://||" | cut -d: -f2 | cut -d/ -f1); \
		NEO4J_PORT="$${NEO4J_PORT:-7687}"; \
		nc -z -w 3 "$$NEO4J_HOST" "$$NEO4J_PORT" \
			&& printf "  $(GREEN)Neo4j OK at $$NEO4J_HOST:$$NEO4J_PORT$(NC)\n" \
			|| { printf "  $(RED)FAIL: Neo4j not reachable at $$NEO4J_HOST:$$NEO4J_PORT$(NC)\n"; exit 1; }; \
		printf "$(GREEN)$(BOLD)All checks passed$(NC)\n"; \
	'

up: ## Start shared infrastructure and API/UI services
	@docker compose -f docker-compose.local.yml up -d

down: ## Stop shared infrastructure and API/UI services
	@docker compose -f docker-compose.local.yml down

serve: ## Start API and UI together
	@$(MAKE) --no-print-directory serve-api & \
	$(MAKE) --no-print-directory serve-ui && \
	wait

serve-api: reasoning-serve-api ## Alias for reasoning-serve-api

serve-ui: ui-dev ## Alias for ui-dev

ui-install: ## Install the Next.js UI dependencies
	@cd $(UI_DIR) && $(UI_PACKAGE_MANAGER) install

ui-dev: ## Start the Next.js UI in dev mode
	@cd $(UI_DIR) && $(UI_PACKAGE_MANAGER) run dev

ui-build: ## Build the Next.js UI
	@cd $(UI_DIR) && $(UI_PACKAGE_MANAGER) run build

ui-start: ## Build (if needed) and start the Next.js UI in production mode
	@test -d $(UI_DIR)/.next || { echo "No production build found — running ui-build first..."; $(MAKE) --no-print-directory ui-build; }
	@cd $(UI_DIR) && $(UI_PACKAGE_MANAGER) run start

fetch: acquisition-fetch ## Fetch PDFs via data-acquisition

ingest: ## Run ingestion pipeline then build knowledge graph (N=<max-pdfs>)
	@printf "$(BLUE)Starting Ingestion Pipeline (N=$(N))...$(NC)\n"
	@cd $(INGESTION_DIR) && \
		python3 scripts/run_pipeline.py --config ../$(CONFIG_FILE) --max-pdfs "$(N)" --skip-graph $(if $(SKIP),--skip-$(SKIP),)
	@printf "$(BLUE)Building Neo4j knowledge graph...$(NC)\n"
	@$(MAKE) --no-print-directory ingestion-neo4j-build
	@printf "$(GREEN)$(BOLD)Ingestion complete.$(NC)\n"

benchmark-sepsis: ## Run the Sepsis Falsification paper through the full pipeline and query agent
	@SPDF=$$(find data/pdfs -name "sepsis_falsification.pdf" -type f 2>/dev/null | head -1); \
	 test -n "$$SPDF" || { printf "$(RED)FAIL: sepsis_falsification.pdf not found under data/pdfs/$(NC)\n"; exit 1; }; \
	 mkdir -p data/pdfs/benchmarks; \
	 cp "$$SPDF" data/pdfs/benchmarks/sepsis_falsification.pdf; \
	 printf "$(YELLOW)Running Falsification Benchmark on Sepsis Models...$(NC)\n"; \
	 cd $(INGESTION_DIR) && python3 scripts/run_pipeline.py --config ../$(CONFIG_FILE) \
		--input-dir ../data/pdfs/benchmarks --skip-graph
	@$(MAKE) --no-print-directory ingestion-neo4j-build
	@$(MAKE) --no-print-directory reasoning-run-query \
		QUERY="Analyze the care-process intensity vs biological signal findings in this paper."

benchmark-all: ## Run the full evaluation harness and generate report (RUN_DIR auto-generated)
	@printf "$(BOLD)$(BLUE)═══ Benchmark Suite — $(RUN_DIR) ═══$(NC)\n"
	@mkdir -p "$(RUN_DIR)"
	@BENCH_RUN_ID="bench_$(RUN_DATE)_$(RUN_HASH)" $(MAKE) --no-print-directory benchmark-provenance RUN_DIR="$(RUN_DIR)"
	@BENCH_RUN_ID="bench_$(RUN_DATE)_$(RUN_HASH)" $(MAKE) --no-print-directory benchmark-retrieval RUN_DIR="$(RUN_DIR)"
	@BENCH_RUN_ID="bench_$(RUN_DATE)_$(RUN_HASH)" $(MAKE) --no-print-directory benchmark-extraction RUN_DIR="$(RUN_DIR)"
	@BENCH_RUN_ID="bench_$(RUN_DATE)_$(RUN_HASH)" $(MAKE) --no-print-directory benchmark-inference RUN_DIR="$(RUN_DIR)"
	@$(MAKE) --no-print-directory benchmark-report RUN_DIR="$(RUN_DIR)"
	@printf "$(GREEN)$(BOLD)Full benchmark complete → $(RUN_DIR)/report.md$(NC)\n"

benchmark-provenance: ## Capture provenance manifest for the current run
	@printf "$(CYAN)Capturing provenance …$(NC)\n"
	@mkdir -p "$(RUN_DIR)"
	@BENCH_RUN_ID_ARG="$${BENCH_RUN_ID:-bench_$(RUN_DATE)_$(RUN_HASH)}"; \
	 cd $(BENCHMARKING_DIR) && $(BENCH_PYTHON) provenance.py "$$BENCH_RUN_ID_ARG" \
		> "../$(RUN_DIR)/manifest.json"

benchmark-retrieval: ## Run retrieval evaluation (Recall@K, Precision@K, NDCG@K, MRR, HitRate)
	@printf "$(CYAN)Running retrieval evaluator …$(NC)\n"
	@mkdir -p "$(RUN_DIR)"
	@cd $(BENCHMARKING_DIR) && BENCH_RUN_ID="$${BENCH_RUN_ID:-bench_$(RUN_DATE)_$(RUN_HASH)}" \
		$(BENCH_PYTHON) evaluators/retrieval_evaluator.py \
		--golden golden/queries.json \
		--output "../$(RUN_DIR)/retrieval.json" \
		$(_RERANKER_ARGS)

benchmark-extraction: ## Run extraction evaluation (entity/relation F1 vs Neo4j)
	@printf "$(CYAN)Running extraction evaluator …$(NC)\n"
	@mkdir -p "$(RUN_DIR)"
	@cd $(BENCHMARKING_DIR) && BENCH_RUN_ID="$${BENCH_RUN_ID:-bench_$(RUN_DATE)_$(RUN_HASH)}" \
		$(BENCH_PYTHON) evaluators/extraction_evaluator.py \
		--golden-entities golden/sepsis_entities.json \
		--golden-relations golden/sepsis_relationships.json \
		--output "../$(RUN_DIR)/extraction.json"

benchmark-inference: ## Run inference timing evaluation (TTFT, TPOT, throughput)
	@printf "$(CYAN)Running inference evaluator ($(BENCH_RUNS) runs) …$(NC)\n"
	@mkdir -p "$(RUN_DIR)"
	@cd $(BENCHMARKING_DIR) && BENCH_RUN_ID="$${BENCH_RUN_ID:-bench_$(RUN_DATE)_$(RUN_HASH)}" \
		$(BENCH_PYTHON) evaluators/inference_evaluator.py \
		--queries golden/queries.json \
		--runs "$(BENCH_RUNS)" \
		--output "../$(RUN_DIR)/inference.json"

benchmark-report: ## Generate Markdown report from a completed run dir (RUN_DIR=...)
	@test -n "$(RUN_DIR)" || { printf "$(RED)FAIL: RUN_DIR is required$(NC)\n"; exit 1; }
	@printf "$(CYAN)Generating report → $(RUN_DIR)/report.md$(NC)\n"
	@cd $(BENCHMARKING_DIR) && $(BENCH_PYTHON) reporter.py \
		--run-dir "../$(RUN_DIR)" \
		--output "../$(RUN_DIR)/report.md"
	@printf "$(GREEN)Report ready: $(RUN_DIR)/report.md$(NC)\n"

# ─── [ Deterministic end-to-end run ] ─────────────────────────────────────────
# Executes the full pipeline from a clean slate through to a final manifest.json
# that embeds provenance, pipeline timings, and all benchmark metrics.
#
#   Phases:
#     1  Preflight  — validate all services are reachable
#     2  Reset      — wipe artifacts, Qdrant collection, Neo4j graph
#     3  Ingest     — OCR → Markdown → clean → chunk → embed (golden PDF only)
#     4  Graph      — build Neo4j knowledge graph from chunks
#     5  Provenance — capture git commit, config hashes, model names, data hashes
#     6  Retrieval  — Recall@K, Precision@K, NDCG@K, MRR, HitRate (bootstrap CIs)
#     7  Extraction — entity/relation F1 (exact + relaxed) vs Neo4j
#     8  Inference  — TTFT, TPOT, throughput across $(BENCH_RUNS) independent runs
#     9  Finalize   — merge all stage JSONs → single manifest.json + report.md
#
#   Override the golden PDF:  make deterministic-run BENCH_PDF=data/pdfs/my.pdf
#   Override inference runs:  make deterministic-run BENCH_RUNS=5

deterministic-run: ## ★ Full deterministic pipeline → single manifest.json (wipe → ingest → KG → benchmark)
	@printf "\n$(BOLD)$(BLUE)═══════════════════════════════════════════════════════════$(NC)\n"
	@printf "$(BOLD)$(BLUE)  DETERMINISTIC RUN  $(DET_RUN_ID)$(NC)\n"
	@printf "$(BOLD)$(BLUE)  PDF: $(BENCH_PDF)$(NC)\n"
	@printf "$(BOLD)$(BLUE)═══════════════════════════════════════════════════════════$(NC)\n\n"
	@mkdir -p "$(DET_RUN_DIR)"
	@printf "$(CYAN) 1/9$(NC) Preflight: validating services …\n"
	@$(MAKE) --no-print-directory validate
	@printf "\n$(CYAN) 2/9$(NC) Reset: wiping artifacts, vectors, graph …\n"
	@$(MAKE) --no-print-directory clean-artifacts
	@$(MAKE) --no-print-directory clean-vectors
	@$(MAKE) --no-print-directory clean-graph
	@printf "\n$(CYAN) 3/9$(NC) Ingest: OCR → Markdown → clean → chunk → embed …\n"
	@$(MAKE) --no-print-directory _det-ingest-timed DET_RUN_DIR="$(DET_RUN_DIR)"
	@printf "\n$(CYAN) 4/9$(NC) Graph: building Neo4j knowledge graph …\n"
	@$(MAKE) --no-print-directory _det-graph-timed DET_RUN_DIR="$(DET_RUN_DIR)"
	@printf "\n$(CYAN) 5/9$(NC) Provenance: capturing git, config, model, data hashes …\n"
	@BENCH_RUN_ID="$(DET_RUN_ID)" \
	 $(MAKE) --no-print-directory benchmark-provenance RUN_DIR="$(DET_RUN_DIR)"
	@printf "\n$(CYAN) 6/9$(NC) Retrieval: Recall@K, NDCG, MRR, HitRate (bootstrap CIs) …\n"
	@$(MAKE) --no-print-directory benchmark-retrieval RUN_DIR="$(DET_RUN_DIR)"
	@printf "\n$(CYAN) 7/9$(NC) Extraction: entity/relation F1 vs Neo4j …\n"
	@$(MAKE) --no-print-directory benchmark-extraction RUN_DIR="$(DET_RUN_DIR)"
	@printf "\n$(CYAN) 8/9$(NC) Inference: TTFT/TPOT/throughput ($(BENCH_RUNS) runs × 20 queries) …\n"
	@BENCH_RUN_ID="$(DET_RUN_ID)" \
	 $(MAKE) --no-print-directory benchmark-inference RUN_DIR="$(DET_RUN_DIR)"
	@printf "\n$(CYAN) 9/9$(NC) Finalize: merging stage outputs → manifest.json + report …\n"
	@$(MAKE) --no-print-directory _det-finalize DET_RUN_DIR="$(DET_RUN_DIR)"
	@$(MAKE) --no-print-directory benchmark-report RUN_DIR="$(DET_RUN_DIR)"
	@printf "\n$(GREEN)$(BOLD)✓ Deterministic run complete$(NC)\n"
	@printf "  Run ID:   $(DET_RUN_ID)\n"
	@printf "  Manifest: $(DET_RUN_DIR)/manifest.json\n"
	@printf "  Report:   $(DET_RUN_DIR)/report.md\n"
	@printf "\n  Reproduce:\n"
	@printf "    git checkout $(RUN_HASH) && make deterministic-run\n\n"

_det-ingest-timed: ## [internal] Run ingestion pipeline on the golden PDF, record elapsed time
	@T0=$$(date +%s); \
	 cd $(INGESTION_DIR) && python3 scripts/run_pipeline.py \
	     --config ../$(CONFIG_FILE) \
	     --input-dir "../$(BENCH_PDF_DIR)" \
	     --max-pdfs 1 \
	     --skip-graph; \
	 T1=$$(date +%s); ELAPSED=$$((T1-T0)); \
	 printf '{"stage":"ingest","elapsed_s":%d,"input_dir":"%s","max_pdfs":1}\n' \
	     "$$ELAPSED" "$(BENCH_PDF_DIR)" \
	     > "../$(DET_RUN_DIR)/pipeline_ingest.json"; \
	 printf "$(GREEN)  ✓ Ingest complete in $${ELAPSED}s$(NC)\n"

_det-graph-timed: ## [internal] Build Neo4j KG from chunks, record elapsed time
	@T0=$$(date +%s); \
	 cd $(INGESTION_DIR) && python3 scripts/build_knowledge_graph.py \
	     --config ../$(CONFIG_FILE); \
	 T1=$$(date +%s); ELAPSED=$$((T1-T0)); \
	 printf '{"stage":"graph","elapsed_s":%d}\n' "$$ELAPSED" \
	     > "../$(DET_RUN_DIR)/pipeline_graph.json"; \
	 printf "$(GREEN)  ✓ Graph built in $${ELAPSED}s$(NC)\n"

_det-finalize: ## [internal] Merge all stage JSONs into a single manifest.json
	@cd $(BENCHMARKING_DIR) && $(BENCH_PYTHON) finalize.py \
	     --run-dir "../$(DET_RUN_DIR)"

clean: ingestion-clean ## Remove generated caches and logs

clean-all: ingestion-clean-all ## Remove ingestion outputs and caches

clean-hard: ## Wipe ALL state — artifacts, vectors, graph (use with caution)
	@printf "$(RED)$(BOLD)Wiping all state...$(NC)\n"
	@$(MAKE) --no-print-directory clean-artifacts
	@$(MAKE) --no-print-directory clean-vectors
	@$(MAKE) --no-print-directory clean-graph
	@printf "$(GREEN)State reset to zero.$(NC)\n"

clean-artifacts: ## Remove all generated repo-wide artifacts
	@rm -rf data/artifacts/extract data/artifacts/convert data/artifacts/clean \
		data/artifacts/chunk data/artifacts/ingestion.log 2>/dev/null || true
	@find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@echo "Cleaned generated artifacts"

clean-ocr: ## Remove OCR outputs
	@rm -rf data/artifacts/extract/* 2>/dev/null || true

clean-md: ## Remove markdown and cleaned outputs
	@rm -rf data/artifacts/convert/* data/artifacts/clean/* 2>/dev/null || true

clean-chunks: ## Remove chunk outputs
	@rm -rf data/artifacts/chunk/* 2>/dev/null || true

clean-vectors: ## Delete the Qdrant collection defined in config/app.yaml
	@bash -c ' \
		set -a; test -f .env.local && source .env.local; set +a; \
		QDRANT_URL_VALUE="$${QDRANT_URL:-http://localhost:6333}"; \
		COLLECTION_NAME="$$(python3 -c '"'"'import yaml; print(yaml.safe_load(open("config/app.yaml"))["data_ingestion"]["vectorization"]["collection_name"])'"'"')"; \
		STATUS=$$(curl --silent --output /dev/null --write-out "%{http_code}" --request DELETE "$$QDRANT_URL_VALUE/collections/$$COLLECTION_NAME"); \
		if [ "$$STATUS" = "200" ]; then \
			printf "$(GREEN)Deleted Qdrant collection: $$COLLECTION_NAME$(NC)\n"; \
		elif [ "$$STATUS" = "404" ]; then \
			printf "$(YELLOW)Collection already absent: $$COLLECTION_NAME$(NC)\n"; \
		else \
			printf "$(RED)Unexpected status $$STATUS deleting $$COLLECTION_NAME$(NC)\n"; exit 1; \
		fi; \
	'

clean-graph: ingestion-neo4j-delete ## Delete all Neo4j graph data

reasoning-install: ## Create reasoning venv if needed and install editable package
	@cd $(REASONING_DIR) && \
		([ -x $(REASONING_PYTHON) ] || python3 -m venv .venv) && \
		$(REASONING_PYTHON) -m pip install -e .

reasoning-clean: ## Remove reasoning caches and logs
	@cd $(REASONING_DIR) && \
		find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true && \
		find . -type f -name "*.pyc" -delete 2>/dev/null || true && \
		rm -f log/*.json log/*.jsonl 2>/dev/null || true

reasoning-test: ## Run reasoning pytest suite
	@cd $(REASONING_DIR) && $(REASONING_PYTHON) -m pytest tests/ -v

reasoning-run: ## Run the reasoning CLI interactively (AGENT=<name>)
	@cd $(REASONING_DIR) && $(REASONING_PYTHON) -m src.cli --agent "$(AGENT)"

reasoning-run-query: ## Run one reasoning query (QUERY=...)
	@cd $(REASONING_DIR) && $(REASONING_PYTHON) -m src.cli --agent "$(AGENT)" "$(QUERY)"

reasoning-run-temporal: ## Run the reasoning CLI interactively via Temporal
	@cd $(REASONING_DIR) && $(REASONING_PYTHON) -m src.cli --agent "$(AGENT)" --use-temporal

reasoning-run-temporal-hitl: ## Run the reasoning CLI interactively via Temporal with HITL
	@cd $(REASONING_DIR) && $(REASONING_PYTHON) -m src.cli --agent "$(AGENT)" --use-temporal --human-in-loop

reasoning-temporal-up: ## Start Temporal, Qdrant, and Neo4j for reasoning
	@cd $(REASONING_DIR) && docker compose -p clinical_agents -f infra/docker-compose.yml up -d

reasoning-temporal-down: ## Stop Temporal, Qdrant, and Neo4j for reasoning
	@cd $(REASONING_DIR) && docker compose -p clinical_agents -f infra/docker-compose.yml down

reasoning-temporal-worker: ## Run the Temporal worker
	@cd $(REASONING_DIR) && $(REASONING_PYTHON) -m src.temporal.worker

reasoning-temporal-run: ## Run one Temporal-backed query (QUERY=...)
	@cd $(REASONING_DIR) && $(REASONING_PYTHON) -m src.cli --agent "$(AGENT)" --use-temporal "$(QUERY)"

reasoning-temporal-run-hitl: ## Run one Temporal-backed query with HITL (QUERY=...)
	@cd $(REASONING_DIR) && $(REASONING_PYTHON) -m src.cli --agent "$(AGENT)" --use-temporal --human-in-loop "$(QUERY)"

reasoning-graphrag-up: ## Start only GraphRAG backing services for reasoning
	@cd $(REASONING_DIR) && docker compose -p clinical_agents -f infra/docker-compose.graphrag.yml up -d

reasoning-graphrag-down: ## Stop GraphRAG backing services for reasoning
	@cd $(REASONING_DIR) && docker compose -p clinical_agents -f infra/docker-compose.graphrag.yml down

reasoning-services-up: ## Start all reasoning-local services
	@$(MAKE) --no-print-directory reasoning-temporal-up
	@$(MAKE) --no-print-directory reasoning-graphrag-up

reasoning-services-down: ## Stop all reasoning-local services
	@$(MAKE) --no-print-directory reasoning-temporal-down
	@$(MAKE) --no-print-directory reasoning-graphrag-down

reasoning-download-models: ## Download local models used by reasoning
	@cd $(REASONING_DIR) && $(REASONING_PYTHON) -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-en-v1.5', cache_folder='data/models'); print('Model cached to data/models/')"

reasoning-sglang-run: ## Run the SGLang-backed assistant interactively
	@cd $(REASONING_DIR) && SGLANG_BASE_URL=http://localhost:30000/v1 $(REASONING_PYTHON) -m src.cli --agent "$(SGLANG_AGENT)"

reasoning-sglang-run-query: ## Run one reasoning query against SGLang (QUERY=...)
	@cd $(REASONING_DIR) && SGLANG_BASE_URL=http://localhost:30000/v1 $(REASONING_PYTHON) -m src.cli --agent "$(SGLANG_AGENT)" "$(QUERY)"

reasoning-sglang-run-temporal: ## Run the SGLang-backed assistant interactively via Temporal
	@cd $(REASONING_DIR) && SGLANG_BASE_URL=http://localhost:30000/v1 $(REASONING_PYTHON) -m src.cli --agent "$(SGLANG_AGENT)" --use-temporal

reasoning-sglang-run-temporal-hitl: ## Run the SGLang-backed assistant interactively via Temporal with HITL
	@cd $(REASONING_DIR) && SGLANG_BASE_URL=http://localhost:30000/v1 $(REASONING_PYTHON) -m src.cli --agent "$(SGLANG_AGENT)" --use-temporal --human-in-loop

reasoning-temporal-run-sglang: ## Run one Temporal query against SGLang (QUERY=...)
	@cd $(REASONING_DIR) && SGLANG_BASE_URL=http://localhost:30000/v1 $(REASONING_PYTHON) -m src.cli --agent "$(SGLANG_AGENT)" --use-temporal "$(QUERY)"

reasoning-temporal-run-hitl-sglang: ## Run one Temporal HITL query against SGLang (QUERY=...)
	@cd $(REASONING_DIR) && SGLANG_BASE_URL=http://localhost:30000/v1 $(REASONING_PYTHON) -m src.cli --agent "$(SGLANG_AGENT)" --use-temporal --human-in-loop "$(QUERY)"

reasoning-serve-api: ## Start the FastAPI backend
	@cd $(REASONING_DIR) && $(REASONING_PYTHON) -m uvicorn src.server:app --host 0.0.0.0 --port 8000 --reload

simple-ui-serve: ## Serve simple-ui on http://localhost:5500 (run reasoning-serve-api in another terminal first)
	@echo "→  UI:  http://localhost:5500"
	@echo "→  API: http://localhost:8000  (start with: make reasoning-serve-api)"
	@cd simple-ui && python3 -m http.server 5500

acquisition-install: ## Create acquisition venv if needed and install editable package
	@cd $(ACQUISITION_DIR) && \
		([ -x $(ACQUISITION_PYTHON) ] || python3 -m venv .venv) && \
		$(ACQUISITION_PYTHON) -m pip install -e .

acquisition-test: ## Run acquisition storage/unit tests
	@cd $(ACQUISITION_DIR) && $(ACQUISITION_PYTHON) -m pytest tests/ -v -m "not integration"

acquisition-fetch: ## Fetch PDFs (SOURCE=<name> MAX_PDFS=<n>)
	@cd $(ACQUISITION_DIR) && $(ACQUISITION_PYTHON) scripts/fetch_pdfs.py --source "$(SOURCE)" --max-pdfs "$(MAX_PDFS)"

acquisition-source-validate: ## Validate a source fetcher (SOURCE=<name>)
	@cd $(ACQUISITION_DIR) && $(ACQUISITION_PYTHON) src/fetchers/$(FETCHER_SCRIPT) --source "$(SOURCE)" validate

acquisition-source-search: ## Search a source fetcher directly (SOURCE=<name> SEARCH_QUERY=...)
	@test -n "$(SEARCH_QUERY)" || (echo "SEARCH_QUERY is required"; exit 1)
	@cd $(ACQUISITION_DIR) && $(ACQUISITION_PYTHON) src/fetchers/$(FETCHER_SCRIPT) --source "$(SOURCE)" search "$(SEARCH_QUERY)"

acquisition-source-fetch: ## Fetch a specific source record (SOURCE=<name> RECORD_ID=... PDF_TYPE=paper|supplementary)
	@test -n "$(RECORD_ID)" || (echo "RECORD_ID is required"; exit 1)
	@cd $(ACQUISITION_DIR) && $(ACQUISITION_PYTHON) src/fetchers/$(FETCHER_SCRIPT) --source "$(SOURCE)" fetch "$(RECORD_ID)" "$(PDF_TYPE)"

ingestion-install: ## Install ingestion dependencies
	@cd $(INGESTION_DIR) && python3 -m pip install -r requirements.txt

ingestion-test: ## Run all ingestion tests
	@cd $(INGESTION_DIR) && python3 -m pytest tests/ -v

ingestion-test-processors: ## Run ingestion processor tests
	@cd $(INGESTION_DIR) && python3 tests/test_processors.py

ingestion-test-embedder: ## Run ingestion embedder test
	@cd $(INGESTION_DIR) && python3 tests/test_embedder.py

ingestion-test-qdrant: ## Run ingestion Qdrant test
	@cd $(INGESTION_DIR) && python3 tests/test_qdrant.py

ingestion-run: ## Run the ingestion pipeline (N=<max-pdfs> SKIP=<stage>)
	@cd $(INGESTION_DIR) && \
		python3 scripts/run_pipeline.py --config ../$(CONFIG_FILE) --max-pdfs "$(N)" $(if $(SKIP),--skip-$(SKIP),)

ingestion-inspect: ## Inspect ingestion pipeline outputs
	@cd $(INGESTION_DIR) && python3 scripts/inspect_pipeline.py

ingestion-qdrant-up: ## Start Qdrant for ingestion
	@cd $(INGESTION_DIR) && docker compose -f infra/docker-compose.yaml up -d

ingestion-qdrant-down: ## Stop Qdrant for ingestion
	@cd $(INGESTION_DIR) && docker compose -f infra/docker-compose.yaml down

ingestion-qdrant-logs: ## Stream Qdrant logs for ingestion
	@cd $(INGESTION_DIR) && docker compose -f infra/docker-compose.yaml logs -f qdrant

ingestion-qdrant-clear: ## Clear embeddings from Qdrant
	@cd $(INGESTION_DIR) && \
		COLLECTION_NAME="$$(python3 -c 'import yaml; print(yaml.safe_load(open("../$(CONFIG_FILE)", "r", encoding="utf-8"))["data_ingestion"]["vectorization"]["collection_name"])')" && \
		python3 -m src.storage.qdrant_manager -c ../$(CONFIG_FILE) clear "$$COLLECTION_NAME"

ingestion-qdrant-delete: ## Delete the Qdrant collection
	@cd $(INGESTION_DIR) && \
		COLLECTION_NAME="$$(python3 -c 'import yaml; print(yaml.safe_load(open("../$(CONFIG_FILE)", "r", encoding="utf-8"))["data_ingestion"]["vectorization"]["collection_name"])')" && \
		python3 -m src.storage.qdrant_manager -c ../$(CONFIG_FILE) delete "$$COLLECTION_NAME"

ingestion-neo4j-build: ## Build the knowledge graph from chunks
	@cd $(INGESTION_DIR) && python3 scripts/build_knowledge_graph.py --config ../$(CONFIG_FILE)

ingestion-neo4j-delete: ## Delete all Neo4j knowledge graph data
	@cd $(INGESTION_DIR) && python3 scripts/delete_knowledge_graph.py --config ../$(CONFIG_FILE)

ingestion-neo4j-stats: ## Show Neo4j graph statistics
	@cd $(INGESTION_DIR) && \
		python3 -c "import sys; sys.path.insert(0, '.'); \
		from src.config_loader import load_ingestion_config; \
		from scripts.delete_knowledge_graph import KnowledgeGraphDeleter; \
		cfg = load_ingestion_config('../$(CONFIG_FILE)'); \
		d = KnowledgeGraphDeleter(cfg); d.get_graph_stats(); d.close()"

ingestion-list-documents: ## List tracked documents
	@cd $(INGESTION_DIR) && python3 scripts/compare_executions.py list-documents

ingestion-list-executions: ## List executions for DOC=<uuid>
	@test -n "$(DOC)" || (echo "DOC is required"; exit 1)
	@cd $(INGESTION_DIR) && python3 scripts/compare_executions.py list-executions --doc "$(DOC)"

ingestion-compare-runs: ## Compare two executions for DOC=<uuid> EXEC1=<uuid> EXEC2=<uuid>
	@test -n "$(DOC)" || (echo "DOC is required"; exit 1)
	@test -n "$(EXEC1)" || (echo "EXEC1 is required"; exit 1)
	@test -n "$(EXEC2)" || (echo "EXEC2 is required"; exit 1)
	@cd $(INGESTION_DIR) && python3 scripts/compare_executions.py --doc "$(DOC)" --exec1 "$(EXEC1)" --exec2 "$(EXEC2)"

ingestion-clean: ## Remove ingestion caches and logs
	@cd $(INGESTION_DIR) && \
		find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true && \
		find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@rm -f data/artifacts/ingestion.log 2>/dev/null || true

ingestion-clean-all: ingestion-clean ## Remove all ingestion data outputs
	@rm -rf data/artifacts/extract data/artifacts/convert data/artifacts/clean \
		data/artifacts/chunk 2>/dev/null || true
