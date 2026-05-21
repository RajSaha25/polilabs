# polilabs — convenience targets
#
# First-time setup:
#   make install     create .venv, install Python + web deps
#   cp .env.example .env   # then paste in your API keys
#   make build       build the SQLite + Kùzu indexes (~100s, one time)
#   make dev         run the backend (:8000) + the polilabs frontend (:5173)
#
# The v1 corpus (191 bills) is already committed, so `make build` is the
# only build step — it derives the indexes from data/corpus/.

PYTHON  := python3.11
VENV    := .venv
PY      := $(VENV)/bin/python
PIP     := $(VENV)/bin/pip
UVICORN := $(VENV)/bin/uvicorn

.PHONY: dev dev-classic backend frontend-design-a frontend-classic install build index graph eval clean help

help:
	@echo "polilabs targets:"
	@echo "  make install      create .venv + install Python and web deps"
	@echo "  make build        build the SQLite + Kuzu indexes from data/corpus/"
	@echo "  make dev          run backend (:8000) + the polilabs frontend (:5173)"
	@echo "  make dev-classic  run backend + the original Vite frontend (web/)"
	@echo "  make eval         run the agent eval harness (~\$$5-10 in Opus API spend)"
	@echo "  make clean        delete the regenerable indexes"

install: $(VENV)/bin/python
	$(PIP) install -e .
	cd web && npm install

$(VENV)/bin/python:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip

index:
	$(PY) scripts/build_index.py

graph:
	$(PY) scripts/build_kuzu_index.py

build: index graph

# `make dev` runs the backend and the polilabs frontend together
# (make -j2); Ctrl-C stops both. The frontend is web-design-a — a
# no-build static prototype — served on http://localhost:5173/.
# `make dev-classic` runs the original Vite frontend in web/ instead.
dev:
	@$(MAKE) -j2 backend frontend-design-a

dev-classic:
	@$(MAKE) -j2 backend frontend-classic

backend:
	$(UVICORN) server:app --reload --port 8000

frontend-design-a:
	@echo "→ polilabs: open http://localhost:5173/"
	$(PYTHON) -m http.server 5173 --directory web-design-a

frontend-classic:
	cd web && npm run dev

eval:
	$(PY) scripts/run_eval.py

clean:
	@rm -rf data/polilabs.db data/polilabs.db-* data/polilabs.kuzu data/polilabs.kuzu* \
	  && echo "wiped indexes — rebuild with: make build"
