"""/api/v1/admin/embeddings — operate the embedding pipeline manually.

Endpoints:
    POST /admin/embeddings/embed-text       — chunk + embed an ad-hoc string (no DB write)
    POST /admin/embeddings/search           — similarity search against existing chunks
    GET  /admin/embeddings/stats            — chunk counts by owner_type + active model info
    GET  /admin/embeddings/model            — active embedding model row

Single-user / no auth (per ADR-0001) but logged loudly. Plan 13 will wire
``embed_owner`` into the SME / messaging / audience service create paths so
embeddings happen automatically on entity creation.
"""

from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.db.models.vectors import DocumentChunk
from app.db.session import DbSession
from app.services.embeddings import (
    chunk_text,
    embed_owner,
    get_active_embedding_model,
    similar_chunks,
)

log = structlog.get_logger("scout.api.admin_embeddings")
router = APIRouter(prefix="/api/v1/admin/embeddings", tags=["admin.embeddings"])


# ---------------------------------------------------------------------------
# Request / response shapes
# ---------------------------------------------------------------------------
class EmbedTextRequest(BaseModel):
    """Ad-hoc embed: writes nothing to vectors.document_chunks."""

    model_config = ConfigDict(extra="forbid")
    text: str = Field(..., min_length=1)
    purpose: str = "admin_embed_text"


class EmbedOwnerRequest(BaseModel):
    """Persist chunks against a real owner. Idempotent (replaces prior chunks)."""

    model_config = ConfigDict(extra="forbid")
    owner_type: str = Field(
        ..., description="messaging / audience / conference / sme_bio / raw_page"
    )
    owner_id: UUID
    text: str
    purpose: str | None = None


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(..., min_length=1)
    owner_types: list[str] | None = None
    k: int = Field(5, ge=1, le=50)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.get("/model")
async def active_model(db: DbSession) -> dict:
    row = await get_active_embedding_model(db)
    return {
        "id": str(row.id),
        "name": row.name,
        "provider": row.provider,
        "dimension": row.dimension,
        "is_active": row.is_active,
    }


@router.get("/stats")
async def chunk_stats(db: DbSession) -> dict:
    """Chunk counts by owner_type, plus the active model info."""
    model_row = await get_active_embedding_model(db)
    result = await db.execute(
        select(DocumentChunk.owner_type, func.count(DocumentChunk.id))
        .group_by(DocumentChunk.owner_type)
        .order_by(DocumentChunk.owner_type)
    )
    by_type = [{"owner_type": row[0], "chunks": int(row[1])} for row in result.all()]
    total = sum(row["chunks"] for row in by_type)
    return {
        "active_model": {
            "id": str(model_row.id),
            "name": model_row.name,
            "dimension": model_row.dimension,
        },
        "total_chunks": total,
        "by_owner_type": by_type,
    }


@router.post("/embed-text")
async def embed_ad_hoc(db: DbSession, payload: EmbedTextRequest) -> dict:
    """Chunk + embed the input text WITHOUT writing to document_chunks.
    Useful for "what would Scout do with this string?" diagnostics."""
    chunks = chunk_text(payload.text)
    if not chunks:
        return {
            "chunks": [],
            "vectors": [],
            "note": "input was empty after normalisation",
        }

    from app.services.llm import EmbeddingRequest, get_llm_client

    response = await get_llm_client().embed(
        EmbeddingRequest(
            texts=[c.text for c in chunks],
            purpose=payload.purpose,
        ),
        db=db,
    )
    await db.commit()  # records the llm_calls row

    return {
        "model": response.model,
        "prompt_tokens": response.prompt_tokens,
        "cost_usd": response.cost_usd,
        "latency_ms": response.latency_ms,
        "chunks": [
            {
                "chunk_index": c.chunk_index,
                "token_count": c.token_count,
                "char_count": len(c.text),
                "text_preview": (c.text[:80] + "…") if len(c.text) > 80 else c.text,
                "vector_dimension": len(v),
                "vector_preview": v[:3],
            }
            for c, v in zip(chunks, response.vectors, strict=True)
        ],
    }


@router.post("/embed-owner")
async def embed_owner_admin(db: DbSession, payload: EmbedOwnerRequest) -> dict:
    """Embed text against a real owner_id. Replaces existing chunks. Idempotent."""
    log.info(
        "admin.embed_owner.invoked",
        owner_type=payload.owner_type,
        owner_id=str(payload.owner_id),
        chars=len(payload.text),
    )
    inserted = await embed_owner(
        db,
        owner_type=payload.owner_type,
        owner_id=payload.owner_id,
        text=payload.text,
        purpose=payload.purpose or f"embed:{payload.owner_type}",
    )
    await db.commit()
    return {
        "owner_type": payload.owner_type,
        "owner_id": str(payload.owner_id),
        "chunks_inserted": inserted,
    }


@router.post("/search")
async def search(db: DbSession, payload: SearchRequest) -> dict:
    """Return top-k chunks similar to the query, optionally filtered by owner_type."""
    hits = await similar_chunks(
        db,
        query=payload.query,
        owner_types=payload.owner_types,
        k=payload.k,
        purpose="admin_search",
        bump_last_used=False,  # diagnostic searches shouldn't pollute decay
    )
    await db.commit()
    return {
        "query": payload.query,
        "k": payload.k,
        "hits": [
            {
                "id": str(h.id),
                "owner_type": h.owner_type,
                "owner_id": str(h.owner_id),
                "chunk_index": h.chunk_index,
                "text_preview": (h.text[:120] + "…") if len(h.text) > 120 else h.text,
                "token_count": h.token_count,
            }
            for h in hits
        ],
    }
