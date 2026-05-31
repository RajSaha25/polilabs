# polilabs backend — FastAPI agent (POST /chat) + read-only REST surface
# (GET /api/*) over the SQLite FTS and Kùzu graph indexes.
#
# The index files (data/polilabs.db, data/polilabs.kuzu) are gitignored and
# fully regenerable, so this image rebuilds them from the committed
# data/corpus/ USLM XML at build time. Building the indexes needs no API key
# — only running the agent (POST /chat) does, via the ANTHROPIC_API_KEY env
# var supplied by the host at runtime.
FROM python:3.11-slim

WORKDIR /app

# Copy the repo (the .dockerignore trims the .venv, the prebuilt indexes,
# both frontends, and other non-runtime files from the build context).
COPY . .

# Install polilabs and its dependencies. `-e .` resolves deps from
# pyproject.toml; the source is already present from the COPY above.
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -e .

# Derive the SQLite FTS index (~30s) and the Kùzu graph (~70s) from
# data/corpus/. Both scripts are destructive + re-runnable; here they build
# the indexes fresh into the image.
#
# `--skip-embeddings` is critical: the fastembed/bge-small dense pass is
# multi-hour on the depot builder (see HANDOFF_EMBED_PASS.md) and reliably
# times out the build session. The dense leg of search_corpus gracefully
# degrades to BM25-only when section_embeddings is empty, so the agent
# still works — semantic re-ranking is added back by shipping a polilabs.db
# that already has the embedding pass run against it.
RUN python scripts/build_index.py --skip-embeddings \
    && python scripts/build_kuzu_index.py

# Documents the default port; the real port is taken from $PORT at runtime.
EXPOSE 8000

# Railway / Render / Fly inject $PORT; fall back to 8000 for a local
# `docker run`. server.py's FastAPI app is `app`.
CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000}"]
