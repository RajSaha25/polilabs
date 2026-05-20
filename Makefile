# polilabs — convenience targets
#
# First-time setup:
#   make install     create .venv, install Python + web deps
#   cp .env.example .env   # then paste in your API keys
#   make build       build the SQLite + Kùzu indexes (~100s, one time)
#   make dev         run the backend (:8000) + the web frontend (:5173)
#
# The v1 corpus (191 bills) is already committed, so `make build` is the
# only build step — it derives the indexes from data/corpus/.

PYTHON  := python3.11
VENV    := .venv
PY      := $(VENV)/bin/python
PIP     := $(VENV)/bin/pip
UVICORN := $(VENV)/bin/uvicorn

.PHONY: dev backend frontend design-a install build index graph eval clean help

help:
	@echo "polilabs targets:"
	@echo "  make install   create .venv + install Python and web deps"
	@echo "  make build     build the SQLite + Kuzu indexes from data/corpus/"
	@echo "  make dev       run backend (:8000) + web frontend (:5173)"
	@echo "  make design-a  serve the web-design-a frontend (:5174); needs the backend"
	@echo "  make eval      run the agent eval harness (~\$$5-10 in Opus API spend)"
	@echo "  make clean     delete the regenerable indexes"

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

# Runs the FastAPI backend and the Vite dev server concurrently
# (make -j2). Ctrl-C stops both. The Vite dev server proxies /api and
# /chat to the backend, so open http://localhost:5173.
dev:
	@$(MAKE) -j2 backend frontend

backend:
	$(UVICORN) server:app --reload --port 8000

frontend:
	cd web && npm run dev

# Serves the parallel web-design-a frontend — a no-build static
# prototype (React via Babel-in-browser), so there is nothing to
# compile. The backend must already be running (`make dev` or
# `make backend`); both frontends share it. Runs alongside `make dev`,
# so the two designs can be compared side by side.
design-a:
	@echo "→ web-design-a: open http://localhost:5174/Polilabs.html"
	@echo "  (the backend must be running — e.g. via 'make dev')"
	$(PYTHON) -m http.server 5174 --directory web-design-a

eval:
	$(PY) scripts/run_eval.py

clean:
	@rm -rf data/polilabs.db data/polilabs.db-* data/polilabs.kuzu data/polilabs.kuzu* \
	  && echo "wiped indexes — rebuild with: make build"
