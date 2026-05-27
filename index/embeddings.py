"""Dense embedding pipeline for polilabs hybrid retrieval.

Uses fastembed (ONNX Runtime) so the deploy footprint stays small —
sentence-transformers would pull torch (~3 GB), and ChromaDB / Pinecone
would add a separate process. At corpus scale (~43k sections × 384 dim
~= 66 MB), a SQLite blob column + in-Python cosine sweep is cheaper than
either alternative.

Model is BAAI/bge-small-en-v1.5: 384-dim, MIT license, CPU-friendly, and
specifically strong on policy/legal English. fastembed downloads its own
quantized ONNX bundle to ~/.cache/huggingface/ on first use (~130 MB).

The module exposes:
  - `MODEL_VERSION` — string written into section_embeddings.model_version
  - `EMBED_DIM` — sanity-check value
  - `embed_corpus(conn, *, batch_size, verbose)` — populates section_embeddings
  - `embed_query(text)` — returns one np.ndarray (float32, shape (384,))
"""
from __future__ import annotations

# CPU politeness: ONNX Runtime + OpenMP default to one thread per core.
# On an 8-12 core laptop that pins the machine and kills foreground
# responsiveness during a build. Cap to 2 threads by default; override
# with POLILABS_EMBED_THREADS for batch boxes / CI. Set BEFORE any
# onnxruntime / fastembed import.
import os as _os
_EMBED_THREADS = _os.environ.get("POLILABS_EMBED_THREADS", "2")
_os.environ.setdefault("OMP_NUM_THREADS", _EMBED_THREADS)
_os.environ.setdefault("MKL_NUM_THREADS", _EMBED_THREADS)
_os.environ.setdefault("OPENBLAS_NUM_THREADS", _EMBED_THREADS)
_os.environ.setdefault("VECLIB_MAXIMUM_THREADS", _EMBED_THREADS)
_os.environ.setdefault("NUMEXPR_NUM_THREADS", _EMBED_THREADS)

import sqlite3
import time
from typing import Iterable

import numpy as np

# Identifier baked into every row's model_version so a future model swap
# is detectable. Bump when the model changes or when the embedding
# normalization scheme changes.
MODEL_NAME = "BAAI/bge-small-en-v1.5"
MODEL_VERSION = "bge-small-en-v1.5@onnx-fastembed"
EMBED_DIM = 384

# Cap per-section text length fed to the encoder. bge-small has a 512-
# token cap; passing longer text just gets truncated by the tokenizer
# anyway. Pre-truncating at the character layer keeps log/cache lines
# predictable and avoids OOM on the few outlier multi-thousand-token
# sections in the corpus.
MAX_CHARS = 2000

# Lazy singleton — the model is heavy to construct (loads ONNX file +
# tokenizer ~1.5 s). We share one across embed_corpus + embed_query.
_MODEL = None


def _get_model():
    """Load fastembed.TextEmbedding once per process.

    Local import so the hard dependency on fastembed is only paid by
    callers that actually need embeddings. Build-time scripts and the
    query path import it; the agent tools' import graph stays clean
    via the lazy hop through this function.
    """
    global _MODEL
    if _MODEL is None:
        from fastembed import TextEmbedding
        _MODEL = TextEmbedding(MODEL_NAME)
    return _MODEL


def embed_query(text: str) -> np.ndarray:
    """Embed a single query string. Returns a float32 vector of shape
    (EMBED_DIM,). Normalized to unit length so cosine == dot product.

    bge-small's docs say to prepend the prefix
    `"Represent this sentence for searching relevant passages: "` to
    asymmetric query embeddings (vs. the no-prefix passages). We do
    that to match the model's training distribution.
    """
    model = _get_model()
    prefixed = f"Represent this sentence for searching relevant passages: {text[:MAX_CHARS]}"
    vec = next(iter(model.embed([prefixed])))
    v = np.asarray(vec, dtype=np.float32)
    n = float(np.linalg.norm(v))
    return v / n if n else v


def _normalize_rows(M: np.ndarray) -> np.ndarray:
    """In-place row-normalize a (N, D) matrix to unit length."""
    norms = np.linalg.norm(M, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    return (M / norms).astype(np.float32, copy=False)


def embed_corpus(
    conn: sqlite3.Connection,
    *,
    batch_size: int = 32,
    verbose: bool = True,
    resume: bool = True,
) -> dict:
    """Compute and store an embedding for every section.

    Per-batch commits make progress durable: if the process is killed
    half-way through (or the user Ctrl-Cs), rerunning with resume=True
    (the default) picks up at the first unembedded section. resume=False
    clears the table first for a clean rebuild.

    Returns counts {rows_embedded, sections_skipped, elapsed_s, resumed_at}.
    """
    import sys
    started = time.monotonic()
    model = _get_model()

    if not resume:
        conn.execute("DELETE FROM section_embeddings")
        conn.commit()

    # Counts first (cheap), THEN open the streaming cursor. Holding all
    # ~43k rows in Python lists materialized ~200 MB — under memory
    # pressure that triggered swap and tanked encoding throughput. We
    # iterate the cursor lazily and only keep the current batch in RAM.
    total_to_encode = conn.execute("""
        SELECT COUNT(*)
        FROM sections s
        LEFT JOIN section_embeddings e ON e.section_id = s.section_id
        WHERE e.section_id IS NULL
    """).fetchone()[0]
    already_embedded = conn.execute(
        "SELECT COUNT(*) FROM section_embeddings"
    ).fetchone()[0]
    if verbose:
        print(f"[embed] {total_to_encode} sections to encode "
              f"(model={MODEL_NAME}, batch={batch_size}, dim={EMBED_DIM}, "
              f"already_embedded={already_embedded})", flush=True)

    # Use a dedicated cursor so the iteration isn't interrupted by other
    # statements on the connection. arraysize controls server-side
    # prefetch — small value keeps Python-side row buffer tiny.
    cur = conn.cursor()
    cur.arraysize = batch_size
    cur.execute("""
        SELECT s.section_id, s.bill_id, b.topic,
               COALESCE(NULLIF(s.heading, ''), '') AS heading,
               COALESCE(NULLIF(s.text_full, ''), '') AS text
        FROM sections s
        JOIN bills b ON b.bill_id = s.bill_id
        LEFT JOIN section_embeddings e ON e.section_id = s.section_id
        WHERE e.section_id IS NULL
    """)

    skipped = 0
    written = 0
    buf_texts: list[str] = []
    buf_meta: list[tuple] = []  # (section_id, bill_id, topic)
    last_log = time.monotonic()

    def _flush():
        nonlocal written
        if not buf_texts:
            return
        # Materialize one batch at a time — no list-of-all-vectors.
        # np.fromiter accumulates into a single pre-allocated buffer.
        n = len(buf_texts)
        M = np.empty((n, EMBED_DIM), dtype=np.float32)
        for i, v in enumerate(model.embed(buf_texts, batch_size=batch_size)):
            M[i] = v
        M = _normalize_rows(M)
        conn.executemany(
            """INSERT OR REPLACE INTO section_embeddings
               (section_id, bill_id, topic, embedding, model_version, dim)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [
                (m[0], m[1], m[2], M[i].tobytes(), MODEL_VERSION, EMBED_DIM)
                for i, m in enumerate(buf_meta)
            ],
        )
        # Per-batch commit: a kill mid-run leaves all already-encoded
        # sections durably stored; re-running picks up from there.
        conn.commit()
        written += len(buf_meta)
        buf_texts.clear()
        buf_meta.clear()

    for r in cur:
        sid, bid, topic, heading, body = r[0], r[1], r[2], r[3], r[4]
        text = (heading + ". " + body).strip()[:MAX_CHARS] if heading else body[:MAX_CHARS]
        if not text:
            skipped += 1
            continue
        buf_texts.append(text)
        buf_meta.append((sid, bid, topic))
        if len(buf_texts) >= batch_size:
            _flush()
            if verbose and time.monotonic() - last_log > 5:
                rate = written / max(time.monotonic() - started, 0.001)
                print(f"  [embed]   {written}/{total_to_encode} encoded ({rate:.0f}/s)",
                      flush=True)
                last_log = time.monotonic()

    _flush()
    elapsed = time.monotonic() - started
    rate = written / max(elapsed, 0.001)
    if verbose:
        print(f"[embed] done: {written} rows in {elapsed:.1f}s "
              f"(skipped {skipped} empty), {rate:.0f} rows/s", flush=True)
    return {
        "rows_embedded": written,
        "sections_skipped": skipped,
        "elapsed_s": round(elapsed, 1),
        "model_version": MODEL_VERSION,
        "dim": EMBED_DIM,
        "resumed_at": already_embedded,
    }


def load_topic_matrix(conn: sqlite3.Connection, topic: str) -> tuple[list[str], list[str], np.ndarray]:
    """Read all embeddings for a topic into memory.

    Returns (section_ids, bill_ids, matrix) where matrix is shape
    (N, EMBED_DIM), already unit-normalized so cosine == matrix @ query.
    Cached at the api layer; this function is the cache miss path.
    """
    rows = conn.execute(
        "SELECT section_id, bill_id, embedding FROM section_embeddings WHERE topic = ?",
        (topic,),
    ).fetchall()
    if not rows:
        return [], [], np.zeros((0, EMBED_DIM), dtype=np.float32)
    sids = [r["section_id"] for r in rows]
    bids = [r["bill_id"] for r in rows]
    M = np.frombuffer(
        b"".join(r["embedding"] for r in rows),
        dtype=np.float32,
    ).reshape(len(rows), EMBED_DIM)
    # The embeddings were normalized at write time, but a defensive
    # re-normalize is cheap and guards against any future drift in the
    # writer path.
    return sids, bids, _normalize_rows(M.copy())
