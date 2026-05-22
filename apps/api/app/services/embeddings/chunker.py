"""Text chunker for the embedding pipeline.

For Phase 1 plain text (manual messaging entries, SME bios, audience
descriptions, scraped page text) we use a sentence-aware character chunker.

Plan 12 (PDF/RAG) introduces ``docling.chunking.HybridChunker`` for
layout-aware chunking on real documents (tables, sections, page numbers).
At that point this module gains a `chunk_doc()` companion that takes a
``DoclingDocument`` and emits ChunkData with structural metadata; plain-text
inputs keep calling ``chunk_text()`` below.

Sizing target: ~750 tokens per chunk at ~4 chars/token = ~3000 chars,
with 300-char overlap on adjacent chunks. Matches the embedder's 4k-token
context budget per call (nomic-embed-text-v1-5 via LLM API).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Sentence boundary heuristic: '.', '!', '?' followed by whitespace + capital
# letter. Imperfect (won't catch "Dr. Smith" or "U.S.A.") but adequate for
# the slightly-noisy text we chunk. Plan 12's Docling-based chunker improves on this.
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-Z\(\"])")

# Token estimation: rough avg of 4 chars per token. Good enough for budget
# bookkeeping; the embedder reports actual token counts.
_CHARS_PER_TOKEN = 4

DEFAULT_MAX_CHARS = 3000
DEFAULT_OVERLAP_CHARS = 300


@dataclass(slots=True)
class ChunkData:
    """One chunk produced by the chunker.

    `metadata` is a free-form dict that plan 12 fills with Docling info
    (section_heading, page_number, content_type). For plain-text inputs it
    stays empty.
    """

    text: str
    chunk_index: int
    token_count: int
    metadata: dict[str, Any] = field(default_factory=dict)


def chunk_text(
    text: str,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> list[ChunkData]:
    """Split `text` into overlapping, sentence-aware chunks.

    Behaviour:
      * Strips leading/trailing whitespace; collapses runs of whitespace to single spaces.
      * Returns [] for empty / whitespace-only input.
      * Greedy: stuffs sentences into chunks up to ``max_chars`` then breaks.
        When a single sentence exceeds ``max_chars``, hard-splits at char boundaries.
      * Adjacent chunks overlap by approximately ``overlap_chars`` (clipped to
        sentence boundary inside the overlap region where possible).
    """
    cleaned = _normalize(text)
    if not cleaned:
        return []
    if len(cleaned) <= max_chars:
        return [_make_chunk(cleaned, 0)]

    sentences = _split_sentences(cleaned)

    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if not current:
            current = sentence
            continue
        if len(current) + 1 + len(sentence) <= max_chars:
            current = f"{current} {sentence}"
        else:
            chunks.append(current)
            # Start new chunk with overlap from the tail of the previous one.
            overlap = _tail_overlap(current, overlap_chars)
            current = f"{overlap} {sentence}".strip() if overlap else sentence
    if current:
        chunks.append(current)

    # Some "sentences" may individually exceed max_chars (a giant URL block,
    # base64 dump in scraped HTML, etc.). Hard-split those.
    expanded: list[str] = []
    for c in chunks:
        if len(c) <= max_chars:
            expanded.append(c)
        else:
            expanded.extend(_hard_split(c, max_chars, overlap_chars))

    return [_make_chunk(t, i) for i, t in enumerate(expanded)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _normalize(text: str) -> str:
    """Strip + collapse whitespace runs to single spaces. Idempotent."""
    return re.sub(r"\s+", " ", text or "").strip()


def _split_sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_BOUNDARY.split(text) if s]


def _tail_overlap(chunk: str, overlap_chars: int) -> str:
    """Return the last ~overlap_chars of `chunk`, clipped to a word boundary."""
    if overlap_chars <= 0 or len(chunk) <= overlap_chars:
        return chunk
    tail = chunk[-overlap_chars:]
    # Snap to next word boundary so we don't start mid-word.
    space = tail.find(" ")
    return tail[space + 1 :] if space != -1 else tail


def _hard_split(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    """Last-resort splitter when a single sentence exceeds max_chars."""
    step = max_chars - overlap_chars
    return [text[i : i + max_chars] for i in range(0, len(text), max(step, 1))]


def _make_chunk(text: str, index: int) -> ChunkData:
    return ChunkData(
        text=text,
        chunk_index=index,
        token_count=max(1, len(text) // _CHARS_PER_TOKEN),
        metadata={},
    )
