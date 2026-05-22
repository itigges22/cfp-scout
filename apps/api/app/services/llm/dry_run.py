"""Deterministic canned responses for ``LLM_DRY_RUN=true``.

Used by:
  * Tests — the whole match pipeline runs offline.
  * Demos / local dev without a real LLM key.
  * CI smoke tests.

Determinism: each call returns the same response for the same input. Chat
responses echo a hash of the messages. Embeddings hash the input text into
a fixed-shape vector via Python's stdlib hashlib.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid

from app.services.llm.models import (
    ChatRequest,
    ChatResponse,
    EmbeddingRequest,
    EmbeddingResponse,
)

# Match nomic-embed-text-v1-5's dimension exactly so the rest of the
# pipeline (pgvector column, HNSW index) doesn't care about dry-run vs real.
DRY_RUN_DIM = 768


def fake_chat(req: ChatRequest) -> ChatResponse:
    """Deterministic chat response. Echoes a short summary + a request id."""
    fingerprint = _hash_messages(req.messages)
    content = (
        f"[dry-run] chat response for purpose={req.purpose!r}, "
        f"fingerprint={fingerprint[:10]}. "
        "Real LLM API calls require LLM_DRY_RUN=false and a valid LLM_API_KEY."
    )
    prompt_tokens = sum(_estimate_tokens(m.content) for m in req.messages)
    completion_tokens = _estimate_tokens(content)
    return ChatResponse(
        content=content,
        model=req.model or "dry-run",
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=0.0,
        latency_ms=1,
        request_id=str(uuid.uuid4()),
    )


def fake_embed(req: EmbeddingRequest) -> EmbeddingResponse:
    """Deterministic embeddings. Each input text maps to the same vector
    every time, derived from sha256(text) seeded into a normal-ish distribution."""
    vectors = [_text_to_vector(t) for t in req.texts]
    prompt_tokens = sum(_estimate_tokens(t) for t in req.texts)
    return EmbeddingResponse(
        vectors=vectors,
        model=req.model or "dry-run",
        prompt_tokens=prompt_tokens,
        cost_usd=0.0,
        latency_ms=1,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _hash_messages(messages: list) -> str:
    blob = json.dumps([m.model_dump() for m in messages], sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def _estimate_tokens(text: str) -> int:
    """Rough char-based estimate. Real token counts come from the provider
    response; for dry-run we just need something stable for budget math."""
    return max(1, len(text) // 4)


def _text_to_vector(text: str) -> list[float]:
    """Deterministic 768-dim vector. Same text → same vector across calls."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    # Stretch the 32-byte digest into 768 floats by repeating + sliding.
    raw = (digest * ((DRY_RUN_DIM // len(digest)) + 1))[:DRY_RUN_DIM]
    # Map bytes 0..255 to roughly [-1, 1] for sensible cosine behavior.
    return [(b / 127.5) - 1.0 for b in raw]


# Suppress unused-time warning — `time` is exported for testability and
# possible future use.
_ = time  # noqa: F841
