---
adr: "0003"
title: Docling for PDF parsing and structure-aware chunking
status: accepted
date: 2026-05-21
supersedes: ""
superseded_by: ""
---

# 0003 — Docling for PDF parsing and structure-aware chunking

## Context

Scout ingests two kinds of text-heavy input for embedding:

1. **PDFs** uploaded by users (messaging decks, audience profile docs, past-conference summaries) — plan 12
2. **Plain text** entered through the web forms

Both paths feed into the same chunking + embedding pipeline (plan 11), which then writes to `vectors.document_chunks`.

The original Phase 1 plan called for **three** libraries to cover the path:

| Library | Job | Drawback |
|---------|-----|----------|
| `pypdf` | Native PDF text extraction | No layout awareness; tables become garbled text |
| `ocrmypdf` (Tesseract) | OCR fallback for scanned PDFs | ~600MB image hit; separate code path; manual fallback heuristic |
| `langchain-text-splitters` | Chunking (RecursiveCharacterTextSplitter) | Character/token-based; cuts mid-table, separates headings from content |

Three deps, two fallback paths, no structural awareness. Chunk quality suffers on real documents (which have tables, lists, and sections).

A teammate flagged [Docling](https://github.com/DS4SD/docling) — an open-source document conversion + chunking library — as a single replacement.

## Decision

Adopt **Docling** for both PDF parsing (plan 12) and chunking (plan 11). Drop `pypdf`, `ocrmypdf`, and `langchain-text-splitters` from the planned dep set.

Specifically:

- **`docling.document_converter.DocumentConverter`** replaces `pypdf` + `ocrmypdf`. Layout-aware PDF parsing with built-in OCR; output is a `DoclingDocument` with structured sections, tables, lists, and reading order preserved.
- **`docling.chunking.HybridChunker`** replaces `langchain-text-splitters`. Produces tokenizer-aware chunks that respect document structure: section boundaries become chunk boundaries; tables are atomic; headings stay with their content.

Add a `chunk_metadata jsonb` column to `document_chunks` to capture Docling's structural information (section heading, page number, content type) so the agent chat (plan 22) can cite *where* a fact came from, not just *that* it came from chunk N.

## Consequences

**Positive**
- **One library, not three.** Less to maintain, fewer version-skew bugs, simpler Containerfile.
- **Better chunk quality.** Tables stay intact, headings preserved with content, section boundaries honored. Direct impact on matcher quality.
- **Multi-format upside.** Docling also handles DOCX, PPTX, HTML, and images via the same converter. Phase 1 only enables PDF uploads, but enabling .pptx (KubeCon trip-report decks!) or .docx (Word-formatted messaging docs) is a flag-flip away — no new library, no new code path.
- **OCR is automatic.** Docling decides per-page whether to run OCR; no manual "text yield < 100 chars/page" heuristic.
- **Tokenizer parity.** `HybridChunker` accepts a tokenizer; we pair it with the `nomic-embed-text-v1-5` tokenizer so chunk sizes line up exactly with embedding-call token limits. No wasted padding.

**Negative**
- **Image size grows ~500MB-1GB.** Docling ships CPU-only layout-analysis models that load at first import. We accept this for local install; users running on workstations have the disk.
- **First-call latency.** Loading the layout models takes a few seconds. Mitigated by a warm-up call during FastAPI lifespan startup (plan 06) so the user sees the latency once at boot, not on first upload.
- **Heavier integration than a string-splitter.** `HybridChunker` is more configurable than `RecursiveCharacterTextSplitter`; we have to choose tokenizer, max-chunk-tokens, overlap policy. The flexibility is the point but it's more learning curve than `langchain-text-splitters`.
- **Less battle-tested than `pypdf` for niche PDFs.** Pypdf has 10+ years of stress-testing on weird PDFs. Docling is younger. We accept this — pin a Docling version, run our own fixture suite (plan 27 evals), upgrade carefully.

**Neutral**
- The chunking decision is reversible. The `embedding_models` table + reindex job (plan 11) lets us re-chunk + re-embed under a new chunker without losing prior data. Swapping back to `langchain-text-splitters` for a specific case is a code change, not a migration.

## Alternatives considered

- **Status quo: `pypdf` + `ocrmypdf` + `langchain-text-splitters`** — Lost because: three deps, two fallback paths, no structural awareness. Specifically would hurt the matcher on documents with tables (audience profile decks often have them).
- **`unstructured.io`** — Considered. Comparable feature set; popular in the LangChain ecosystem. Lost because: broader scope means more dep surface (it carries lots of optional integrations); Docling's HybridChunker is purpose-built for RAG in a way unstructured's chunker isn't.
- **LlamaParse (paid service)** — Lost because: not a hosted-services tool. Local install means local parsing.
- **Marker** — Considered (it's a smaller, focused PDF→Markdown tool). Lost because: PDF-only; no built-in chunker.
- **Keeping `langchain-text-splitters` and only adopting Docling for PDFs** — Possible but loses the structure-aware chunking win on plain-text inputs too. Better to do both at once.

## Implementation pointers

- Plan 11 (`apps/api/app/services/embeddings/chunker.py`) wraps `HybridChunker` with our tokenizer config.
- Plan 12 (`apps/api/app/tasks/parse_pdf.py`) uses `DocumentConverter` instead of `pypdf` + `ocrmypdf`.
- The `apps/api/Containerfile` py-builder stage pre-warms model downloads so runtime images don't fetch them on first boot.
- FastAPI lifespan (plan 06) calls a 1-page dummy `convert()` at startup to warm the layout models.
- `chunk_metadata jsonb` lands in the initial Alembic baseline migration (plan 06).

## References

- [Docling on GitHub](https://github.com/DS4SD/docling)
- [Docling docs](https://ds4sd.github.io/docling/)
- `apps/api/app/services/extraction/pipeline.py` — parser integration with
  subprocess-isolated tiered fallback (see ADR-0008-equivalent prose in
  `docs/ARCHITECTURE.md` under "OOM hardening")
- [`docs/data-model.md`](../data-model.md) — `document_chunks.chunk_metadata`
  column, operator-facing
