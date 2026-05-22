"""Background embed_owner — re-embeds an owner entity's text outside the
request thread.

The synchronous create/update path in
:mod:`app.services.audience_service` (etc.) still does embedding inline (it's
quick on dry-run + on a single short string), but bulk re-embedding,
post-PDF-upload re-embedding, and any operation that touches many owners at
once should enqueue this task instead.

Usage from a service:
    from app.scheduler import enqueue_now
    from app.tasks.embed_owner_task import embed_owner_task

    enqueue_now(
        embed_owner_task,
        job_id=f"embed-{owner_type}-{owner_id}",
        kwargs={
            "owner_type": owner_type,
            "owner_id": str(owner_id),
            "text": text,
            "purpose": "embed:bulk_reindex",
        },
    )

Notes:
  * ``owner_id`` is passed as a str (JSON-serialisable through APScheduler's
    persistent jobstore); we parse it back here.
  * The wrapped function opens its own DB session — no FastAPI request
    context inside scheduled runs.
"""

from __future__ import annotations

from uuid import UUID

from app.db.session import get_session_factory
from app.services.embeddings import embed_owner
from app.tasks._runner import run_as_job


async def _do_embed(
    *,
    owner_type: str,
    owner_id: str,
    text: str,
    purpose: str = "embed:bulk_reindex",
) -> dict[str, int | str]:
    async with get_session_factory()() as session:
        chunks = await embed_owner(
            session,
            owner_type=owner_type,
            owner_id=UUID(owner_id),
            text=text,
            purpose=purpose,
        )
        await session.commit()
    return {"chunks_inserted": chunks, "owner_type": owner_type, "owner_id": owner_id}


async def embed_owner_task(
    *,
    owner_type: str,
    owner_id: str,
    text: str,
    purpose: str = "embed:bulk_reindex",
) -> dict[str, object]:
    """APScheduler-callable entry point. All kwargs are JSON-serialisable."""
    return await run_as_job(
        f"embed_owner:{owner_type}",
        _do_embed,
        owner_type=owner_type,
        owner_id=owner_id,
        text=text,
        purpose=purpose,
        stats_extra={"owner_id": owner_id, "owner_type": owner_type},
    )
