"""Deterministic canned responses for ``LLM_DRY_RUN=true``.

Used by:
  * Tests — the whole match pipeline runs offline.
  * Demos / local dev without a real MaaS key.
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
    """Deterministic chat response. Echoes a short summary + a request id.

    Plan 15 extraction needs valid JSON output even in dry-run, so the
    ``extract:conference`` purpose dispatches to a canned JSON envelope
    derived from the page text fingerprint. Real MaaS calls require
    LLM_DRY_RUN=false.
    """
    fingerprint = _hash_messages(req.messages)
    if req.purpose == "extract:conference":
        content = _canned_extract_conference(req, fingerprint)
    elif req.purpose == "rationale:match":
        content = _canned_match_rationale(req, fingerprint)
    else:
        content = (
            f"[dry-run] chat response for purpose={req.purpose!r}, "
            f"fingerprint={fingerprint[:10]}. "
            "Real MaaS calls require LLM_DRY_RUN=false and a valid LLM_API_KEY."
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


def _canned_match_rationale(req: ChatRequest, fingerprint: str) -> str:
    """Deterministic rationale text for plan 17 in dry-run mode.

    Echoes a couple of facts from the prompt so a human reading the dry-run
    output can verify the pipeline wired the right snippets, without needing
    a real LLM.
    """
    # Peek at the user message for the conference name and pillar mention so
    # the canned text feels grounded.
    user_msg = next((m.content for m in req.messages if m.role == "user"), "")
    conf_name = "the conference"
    for line in user_msg.splitlines():
        if line.startswith("Conference:"):
            conf_name = line.split(":", 1)[1].strip()
            break
    return (
        f"[dry-run rationale] {conf_name} aligns with the product's messaging "
        f"based on the supplied evidence snippets (fingerprint {fingerprint[:8]}). "
        "Recommended SMEs come from the in-memory graph's topic + audience overlap. "
        "Real LLM rationale lands when LLM_DRY_RUN=false."
    )


def _canned_extract_conference(req: ChatRequest, fingerprint: str) -> str:
    """Deterministic ExtractedConference JSON for plan 15 in dry-run mode.

    Derives a fake but plausible conference name from the page-text hash so
    different pages produce different rows downstream (drives dedupe and
    routing without needing a real LLM). Year is fixed to next year so the
    same-year dedup logic still gets exercised.
    """
    # 16-char hex slug from the fingerprint — different pages, different
    # conferences.
    slug = fingerprint[:16]
    payload = {
        "name": f"Dry-Run Conference {slug.upper()}",
        "start_date": "2027-04-15",
        "end_date": "2027-04-17",
        "location_city": "Boston",
        "location_country": "US",
        "is_virtual": False,
        "venue": "Hynes Convention Center",
        "website": None,
        "cfp_open_at": "2026-09-01",
        "cfp_close_at": "2026-12-15",
        "cfp_deadlines": [
            {
                "kind": "submission",
                "deadline_date": "2026-12-15",
                "description": "Main track papers",
                "applies_to": "talks",
            }
        ],
        "cfp_topics_of_interest": ["large language models", "RAG", "inference"],
        "topics": ["llm", "inference", "rag"],
        "acceptance_rate_percent": 22,
        "estimated_cost_usd": 1200,
        "confidence": 0.78,
    }
    return json.dumps(payload)


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
