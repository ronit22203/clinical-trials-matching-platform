SHELL := /bin/bash

REASONING_DIR := agentic-reasoning
ACQUISITION_DIR := data-acquisition
INGESTION_DIR := data-ingestion
UI_DIR := platform-ui
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

FETCHER_SCRIPT = $(if $(filter clinical_trials,$(SOURCE)),clinical_trials_pdf.py,$(SOURCE).py)

.PHONY: help \
	bootstrap validate up down serve serve-api serve-ui fetch ingest \
	clean clean-all clean-artifacts clean-ocr clean-md clean-chunks clean-vectors clean-graph \
	ui-install ui-dev ui-build ui-start \
	reasoning-install reasoning-clean reasoning-test reasoning-run reasoning-run-query \
	reasoning-run-temporal reasoning-run-temporal-hitl reasoning-temporal-up reasoning-temporal-down \
	reasoning-temporal-worker reasoning-temporal-run reasoning-temporal-run-hitl \
	reasoning-graphrag-up reasoning-graphrag-down reasoning-services-up reasoning-services-down \
	reasoning-download-models reasoning-sglang-run reasoning-sglang-run-query \
	reasoning-sglang-run-temporal reasoning-sglang-run-temporal-hitl \
	reasoning-temporal-run-sglang reasoning-temporal-run-hitl-sglang reasoning-serve-api \
	acquisition-install acquisition-test acquisition-fetch acquisition-source-validate \
	acquisition-source-search acquisition-source-fetch \
	ingestion-install ingestion-test ingestion-test-processors ingestion-test-embedder \
	ingestion-test-qdrant ingestion-run ingestion-inspect ingestion-qdrant-up \
	ingestion-qdrant-down ingestion-qdrant-logs ingestion-qdrant-clear ingestion-qdrant-delete \
	ingestion-neo4j-build ingestion-neo4j-delete ingestion-neo4j-stats \
	ingestion-list-documents ingestion-list-executions ingestion-compare-runs \
	ingestion-clean ingestion-clean-all

help: ## Show all root orchestration targets
	@printf "\nUnified root control surface\n\n"
	@grep -E '^[a-zA-Z0-9_.-]+:.*?## ' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  %-34s %s\n", $$1, $$2}'

bootstrap: ## Bootstrap Python and Node dependencies
	@./scripts/bootstrap.sh

validate: ## Check env file, LM Studio, Qdrant, and Neo4j connectivity
	@bash -c 'set -euo pipefail; \
		test -f .env.local || { echo "FAIL: missing .env.local"; exit 1; }; \
		set -a; source .env.local; set +a; \
		LM_STUDIO_URL="$${LM_STUDIO_BASE_URL:-http://localhost:1234/v1}"; \
		QDRANT_ADDR="$${QDRANT_URL:-http://localhost:6333}"; \
		NEO4J_BOLT="$${NEO4J_URI:-bolt://localhost:7687}"; \
		echo "Checking LM Studio at $$LM_STUDIO_URL"; \
		curl --fail --silent "$$LM_STUDIO_URL/models" >/dev/null && echo "  LM Studio OK" || { echo "  FAIL: LM Studio not reachable"; exit 1; }; \
		echo "Checking Qdrant at $$QDRANT_ADDR"; \
		curl --fail --silent "$$QDRANT_ADDR/collections" >/dev/null && echo "  Qdrant OK" || { echo "  FAIL: Qdrant not reachable"; exit 1; }; \
		echo "Checking Neo4j at $$NEO4J_BOLT"; \
		NEO4J_HOST=$$(echo "$$NEO4J_BOLT" | sed "s|.*://||" | cut -d: -f1); \
		NEO4J_PORT=$$(echo "$$NEO4J_BOLT" | sed "s|.*://||" | cut -d: -f2 | cut -d/ -f1); \
		NEO4J_PORT="$${NEO4J_PORT:-7687}"; \
		nc -z -w 3 "$$NEO4J_HOST" "$$NEO4J_PORT" && echo "  Neo4j OK at $$NEO4J_HOST:$$NEO4J_PORT" || { echo "  FAIL: Neo4j not reachable at $$NEO4J_HOST:$$NEO4J_PORT"; exit 1; }; \
		echo "All checks passed"; \
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

ingest: ingestion-run ## Run the ingestion pipeline

clean: ingestion-clean ## Remove generated caches and logs

clean-all: ingestion-clean-all ## Remove ingestion outputs and caches

clean-artifacts: ## Remove all generated repo-wide artifacts
	@rm -rf data/*.pdf data/processed/*.md data/processed/*.json data/processed/*.chunks.json 2>/dev/null || true
	@rm -rf log/*.json log/*.jsonl 2>/dev/null || true
	@find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@echo "Cleaned generated artifacts"

clean-ocr: ## Remove OCR outputs
	@rm -rf data-ingestion/data/ocr/* 2>/dev/null || true

clean-md: ## Remove markdown and cleaned outputs
	@rm -rf data-ingestion/data/markdown/* data-ingestion/data/cleaned/* 2>/dev/null || true

clean-chunks: ## Remove chunk outputs
	@rm -rf data-ingestion/data/chunks/* 2>/dev/null || true

clean-vectors: ## Delete the Qdrant collection defined in config/app.yaml
	@bash -c 'set -euo pipefail; \
		set -a; test -f .env.local && source .env.local; set +a; \
		QDRANT_URL_VALUE="$${QDRANT_URL:-http://localhost:6333}"; \
		COLLECTION_NAME="$$(python3 -c '"'"'"'"'"'"'"'"'import yaml; print(yaml.safe_load(open("config/app.yaml", "r", encoding="utf-8"))["data_ingestion"]["vectorization"]["collection_name"])'"'"'"'"'"'"'"'"')"; \
		curl --fail --silent --request DELETE "$$QDRANT_URL_VALUE/collections/$$COLLECTION_NAME" >/dev/null; \
		echo "Deleted Qdrant collection $$COLLECTION_NAME"; \
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
		find . -type f -name "*.pyc" -delete 2>/dev/null || true && \
		rm -f logs/*.log 2>/dev/null || true

ingestion-clean-all: ingestion-clean ## Remove all ingestion data outputs
	@rm -rf $(INGESTION_DIR)/data/raw/* $(INGESTION_DIR)/data/ocr/* $(INGESTION_DIR)/data/markdown/* \
		$(INGESTION_DIR)/data/cleaned/* $(INGESTION_DIR)/data/chunks/* 2>/dev/null || true
