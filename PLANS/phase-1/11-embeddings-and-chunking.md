# 11 — Embeddings & Chunking

## Goal
Turn text into vectors via MaaS, store them in pgvector, and design the
pipeline so we can swap embedding models later without losing the corpus.

## Prereqs
- 03 (pgvector)
- 04 (`document_chunks`, `embedding_models`)
- 10 (LLM client)

## Decisions locked

### Embedding model
- **`nomic-embed-text-v1-5` via MaaS** — 768 dim, $0.02/M input, $0.00/M output.
- Confirmed: this is the **only** embedding model exposed on Red Hat MaaS.
  We commit to it. If MaaS adds a stronger embedder later
  (`mxbai-embed-large-v1`, `bge-large-en-v1.5`, etc.), the rollover SOP in
  `docs/ops/embedding-model-change.md` walks the swap. Cost of swap: re-embed
  the corpus (a one-time background job).
- 4k context per call (per MaaS catalog); we batch chunks accordingly.

### Chunk size
- 800 tokens / chunk, 100-token overlap, sentence-aware split.
- Token counts via `tiktoken` (`cl100k_base`) as a portable approximation.

### Index
- **HNSW** on `document_chunks.embedding` with `m=16, ef_construction=64`.
- Cosine distance (`vector_cosine_ops`).

### Versioning
- `embedding_models` table is the source of truth.
- Every chunk carries `embedding_model_id`.
- One model `is_active=true` normally; two during rollover.
- Reindex job re-embeds against the new model.

## Tasks
- [ ] `app/services/embeddings/`:
  - `chunker.py` — sentence-aware split via `langchain-text-splitters`
    (`RecursiveCharacterTextSplitter` with token counts)
  - `pipeline.py` — `embed_owner(owner_type, owner_id, text)`:
    1. Look up active model
    2. Delete prior chunks for this owner under the active model
    3. Chunk text
    4. Batch-embed via LLM client
    5. Insert chunk rows in a single transaction
  - `search.py` — `similar_chunks(query_text, owner_types, k=10) -> list[Chunk]`
- [ ] Initial migration creates the HNSW index. Build it after first batch
      of seed data via `CREATE INDEX CONCURRENTLY` if rows already exist.
- [ ] Admin endpoints (single-user, no auth, but logged loudly):
  - `GET /api/v1/admin/embedding-model`
  - `POST /api/v1/admin/embedding-model/promote`
  - `POST /api/v1/admin/reindex` (enqueues step 13 job)
- [ ] Tests with `LLM_DRY_RUN=true` are deterministic.
- [ ] `docs/ops/embedding-model-change.md` — SOP for swapping models.

## Security notes
- Embedding inputs are user text or scraped text — treated as data, never
  evaluated. Chunker is pure Python.
- Per-call size cap (50k tokens per `embed_owner`); larger inputs split into
  multiple jobs.
- `llm_calls` records token counts and chunk indices, never chunk text.

## Acceptance criteria
- [ ] Embedding a 5-page text doc deterministically produces N chunks.
- [ ] Searching for one of the chunked sentences returns that chunk first.
- [ ] Promoting a (dry-run) new model + reindex re-embeds; both model
      chunks coexist mid-rollover.
- [ ] HNSW index visible via `\d+ document_chunks` and used by `EXPLAIN ANALYZE`.

## Open questions for the user
- **Matryoshka truncation** — nomic supports truncating to 512/384/etc.
  Recommend full 768 for Phase 1; the storage and query cost is negligible
  at our scale.

## Risks
- nomic isn't best-in-class for technical content. If match quality is
  poor, the swap SOP exists; cost is just re-embedding the corpus.
- HNSW build time scales with corpus. Phase 1 stays small. Document `IVFFlat`
  as the alternative for > 1M chunks.
