"""Backfill `vectors.document_chunks` for Conference rows that don't
have any embedding yet.

A no-op when every conference already has at least one chunk. Useful
after a feed-ingest pass that landed conference rows but skipped the
inline embed step.

Run from inside the api container::

    podman exec scout-api /app/.venv/bin/python /app/scripts/backfill_conference_embeddings.py
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.db.models.entities import Conference
from app.db.models.vectors import DocumentChunk
from app.db.session import get_session_factory
from app.services.embeddings import embed_owner
from app.services.extraction.pipeline import _conference_embed_text


async def main(batch_size: int = 25) -> int:
    factory = get_session_factory()
    async with factory() as session:
        # Find conferences with NO chunks.
        rows = (
            (
                await session.execute(
                    select(Conference).where(
                        Conference.id.notin_(
                            select(DocumentChunk.owner_id).where(
                                DocumentChunk.owner_type == "conference"
                            )
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
        total = len(rows)
        print(f"Conferences missing embeddings: {total}", flush=True)
        if total == 0:
            return 0

        ok, fail = 0, 0
        for i, c in enumerate(rows, start=1):
            try:
                blob = _conference_embed_text(c)
                if not blob:
                    fail += 1
                    continue
                await embed_owner(
                    session,
                    owner_type="conference",
                    owner_id=c.id,
                    text=blob,
                    purpose="embed:backfill",
                )
                ok += 1
                if i % batch_size == 0:
                    await session.commit()
                    print(f"  committed {i}/{total} (ok={ok} fail={fail})", flush=True)
            except SQLAlchemyError as exc:
                await session.rollback()
                print(f"  rollback at {i}: {exc}", flush=True)
                fail += 1
            except Exception as exc:
                fail += 1
                print(f"  fail {c.name[:60]}: {exc}", flush=True)

        await session.commit()
        print(f"Done. ok={ok} fail={fail}", flush=True)
        return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
