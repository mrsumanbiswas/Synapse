# Common tasks. Uses Docker Compose when available, otherwise podman-compose.
COMPOSE ?= $(shell if command -v docker >/dev/null 2>&1; then echo "docker compose"; else echo "podman-compose"; fi)

.PHONY: help setup up down logs reset test typecheck dev-backend dev-frontend sample

help:            ## Show this help
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

setup:           ## Install backend (venv) and frontend (npm) dependencies for local development
	cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
	cd frontend && npm install

up:              ## Build and start the 3-node demo cluster (UI on :3000, :3001, :3002)
	$(COMPOSE) up --build -d

down:            ## Stop the demo cluster (data volumes are kept)
	$(COMPOSE) down

logs:            ## Follow the logs of the three nodes
	$(COMPOSE) logs -f node-a node-b node-c

reset:           ## Stop the cluster and delete its data volumes
	$(COMPOSE) down -v

test:            ## Run the backend test suite
	cd backend && .venv/bin/python -m pytest -q

typecheck:       ## Type-check and build the frontend
	cd frontend && npm run build

dev-backend:     ## Run one node locally on :8000 with the sample corpus
	cd backend && SYNAPSE_SEED_SAMPLE=true SYNAPSE_DATA_DIR=./data .venv/bin/python -m synapse serve

dev-frontend:    ## Run the Vite dev server on :5173 against the local node
	cd frontend && SYNAPSE_API=http://127.0.0.1:8000 npm run dev

sample:          ## Re-download the bundled OpenAlex sample corpus
	cd backend && .venv/bin/python -m synapse build-sample openalex --out datasets/openalex_sample.jsonl.gz
