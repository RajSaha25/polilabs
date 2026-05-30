# Handoff: bge-small embed pass for hybrid search

Raj — this is the data-only follow-up to PR #57 (hybrid semantic search). The code is on master; what's missing is the full embedding pass over the corpus, which Andrew's Mac can't run without thermal/UI pressure even at the conservative settings the code already defaults to.

## Why this needs you

During the in-flight runs on 2026-05-27 and 2026-05-30, Andrew explicitly stopped the embed twice with "cpu use is getting high" / "memory pressure" while it was running under `nice -n 19` + `POLILABS_EMBED_THREADS=2` + `--embed-batch 8`. At those settings the embed phase is multi-hour on his box. Your machine should swallow it without notice.

The dense leg of `search_corpus` **gracefully degrades to BM25-only** when `section_embeddings` is empty or partial, so the agent works fine without the embed pass — it just loses the Q5-class semantic wins (the original motivation for #57).

## State on master (as of #62 merge)

- Schema, hybrid retrieval code, agent topic plumbing all shipped (PRs #54 / #56 / #57 / #58 / #59 / #60 / #61 / #62).
- Corpus: **203 bills** (191 ai_governance covering 118th–119th Congress; 12 redistricting seed covering 117th–119th).
- `data/polilabs.db` is gitignored — must be rebuilt locally on each machine.

## State of Andrew's local DB

- Schema is correct (`topic` column present).
- 203 bills + 43,075 sections committed; Kùzu graph fully built.
- **7,880 / 29,616 ai_governance sections embedded** (durable; per-batch commits made the work resumable).
- **0 / 13,459 redistricting sections embedded.**
- Total target: 43,075 sections × 384-dim float32 ≈ 66 MB blob storage in SQLite.

## What you actually need to do

On a machine that can spare cores for ~15–30 min:

```
cd ~/polilabs
git pull
make build      # rebuilds SQLite FTS, Kùzu, AND runs embed pass at default batch=16
```

OR — slow-and-polite (matches what Andrew was running, ~60 min wall):

```
nice -n 19 env POLILABS_EMBED_THREADS=2 \
  python scripts/build_index.py --embed-batch 8
```

OR — if your box is strong (~15 min wall):

```
env POLILABS_EMBED_THREADS=6 python scripts/build_index.py --embed-batch 32
```

**Resume is built in.** If killed mid-run, re-running with `--embed-only` picks up at the first unembedded section via a LEFT JOIN on `section_embeddings`. Partial state is never wasted.

## Verifying the result

```
python scripts/verify_hybrid_search.py
```

Should print `smoke summary: 4/4 passed` with non-zero embedding counts for both `ai_governance` and `redistricting`. The script prints per-topic coverage at the top.

The eval-driven proof point is **Q5** in `eval/agent_eval.py`: the query *"restrict advanced AI chip exports to foreign adversaries"*. After the full embed, the agent should surface the **CLOUD AI Act** (118-hr-4683), the **GAIN AI Act** (119-hr-5885), and likely **Full AI Stack Export Promotion Act** (119-hr-6996). Pre-#57 (BM25-only) the agent missed all three.

## Where the embeddings need to land

**For local testing** — `data/polilabs.db` just needs to exist on the box running `make dev` or the eval.

**For prod (Fly: `polilabs-backend.fly.dev`)** — you manage the Fly deploy, so the question is whether the deploy:

1. ships `data/polilabs.db` as a release artifact (requires the build to happen during the Fly Docker build, or for the file to be uploaded to a Fly volume), or
2. builds the DB inside the Fly container on start.

Either way, the embed pass needs to run wherever `polilabs.db` is being produced. The current Fly deploy is at server build date 2026-05-26 per its `server` header, so it likely has zero embeddings; serving from that path means BM25-only on the live demo.

## CPU politeness defaults already in the code

`index/embeddings.py` sets these env vars **before** the ONNX import:

- `OMP_NUM_THREADS`, `MKL_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, `VECLIB_MAXIMUM_THREADS`, `NUMEXPR_NUM_THREADS`

All default to `POLILABS_EMBED_THREADS` (default `2`). Stricter limit: `export POLILABS_EMBED_THREADS=1`.

## Stack snapshot

- Embedding model: `BAAI/bge-small-en-v1.5` (384-dim, MIT license, ~130 MB ONNX, downloaded to `~/.cache/huggingface/` on first run).
- Runtime: fastembed (ONNX Runtime), no torch.
- Storage: `section_embeddings(section_id PK, bill_id, topic, embedding BLOB, model_version, dim)` in the SQLite index. No vector-search extension; query-time uses a NumPy cosine sweep against a per-topic matrix.
- Fusion: Reciprocal Rank Fusion (k=60) over BM25 + dense.
- Gate: dense leg only contributes when BM25 found ≥1 in-topic hit — empirical fix from #57. bge-small's absolute cosines hover at 0.4–0.6 even for off-topic queries, so a raw top-N from dense without the lexical anchor was flooding results with noise.

## Vercel side-quest (unrelated to embed, but worth knowing)

PR #60 and #62 did **not** auto-deploy to Vercel. The cache-buster bumps in `web-design-a/Polilabs.html` are pointless if the underlying JSX/CSS files aren't refreshed on the CDN. Trigger a manual redeploy from the Vercel dashboard for the polilabs project after merging anything that touches `web-design-a/`. Worth checking the project's auto-deploy settings (production branch = `master`, GitHub integration connected, "ignored build step" not too restrictive) while you're in there.
