.DEFAULT_GOAL := help
VENV         := .venv
PYTHON       := $(VENV)/bin/python
PIP          := $(VENV)/bin/pip
UVICORN      := $(VENV)/bin/uvicorn
PORT         := 8765

# Load .env if present (exports ANTHROPIC_API_KEY etc. to docker compose)
-include .env
export

.PHONY: help up down logs install run ingest ingest-% clean release

help:
	@echo ""
	@echo "  Docker (recommended)"
	@echo "  make up              Build image and start container (http://localhost:$(PORT))"
	@echo "  make down            Stop container  — data in ./data/ is never deleted"
	@echo "  make logs            Follow container logs"
	@echo ""
	@echo "  Release"
	@echo "  make release VERSION=v1.2.3   Tag and push — triggers GHCR image build"
	@echo ""
	@echo "  Local development"
	@echo "  make install         Create .venv and install dependencies"
	@echo "  make run             Start dev server with --reload (http://localhost:$(PORT))"
	@echo "  make ingest          Ingest all sources into data/terms.db"
	@echo "  make ingest-SOURCE   Ingest one source  (e.g. make ingest-cfihos)"
	@echo ""
	@echo "  make clean           Remove .venv and __pycache__"
	@echo ""

# ── Docker ────────────────────────────────────────────────────────────────────

up:
	docker compose up -d --build

release:
ifndef VERSION
	$(error VERSION is required. Usage: make release VERSION=v1.2.3)
endif
	@echo "Creating release $(VERSION)…"
	git tag $(VERSION) -m "Release $(VERSION)"
	git push origin $(VERSION)
	@echo "Tag pushed — GitHub Actions will build ghcr.io/n0santos/copieditor:$(VERSION)"

down:
	docker compose down

logs:
	docker compose logs -f

# ── Local ─────────────────────────────────────────────────────────────────────

install:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

run:
	$(UVICORN) app.main:app --reload --port $(PORT)

ingest:
	$(PYTHON) -m scripts.ingest

ingest-%:
	$(PYTHON) -m scripts.ingest --source $*

clean:
	rm -rf $(VENV) __pycache__ **/__pycache__ **/*.pyc
