# polilabs — convenience targets
#
# First-time setup:
#   make install     create .venv and install dependencies
#   cp .env.example .env   # then paste in your API keys
#   make build       build the SQLite + Kùzu indexes (~100s, one time)
#   make dev         run the backend on http://localhost:8000
#
# The v1 corpus (191 bills) is already committed, so `make build` is the
# only build step — it derives the indexes from data/corpus/.

PYTHON  := python3.11
VENV    := .venv
PY      := $(VENV)/bin/python
PIP     := $(VENV)/bin/pip
UVICORN := $(VENV)/bin/uvicorn

.PHONY: dev backend install build index graph eval clean help

help:
	@echo "polilabs targets:"
	@echo "  make install   create .venv + install deps"
	@echo "  make build     build the SQLite + Kuzu indexes from data/corpus/"
	@echo "  make dev       run the FastAPI backend on :8000 (auto-reload)"
	@echo "  make eval      run the agent eval harness (~\$$5-10 in Opus API spend)"
	@echo "  make clean     delete the regenerable indexes"

install: $(VENV)/bin/python
	$(PIP) install -e .

$(VENV)/bin/python:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip

index:
	$(PY) scripts/build_index.py

graph:
	$(PY) scripts/build_kuzu_index.py

build: index graph

# Phase 0: backend only. The web/ frontend (Phase 1) extends this target
# to also run `npm run dev` for the Vite dev server, concurrently.
dev: backend

backend:
	$(UVICORN) server:app --reload --port 8000

eval:
	$(PY) scripts/run_eval.py

clean:
	@rm -rf data/polilabs.db data/polilabs.db-* data/polilabs.kuzu data/polilabs.kuzu* \
	  && echo "wiped indexes — rebuild with: make build"
