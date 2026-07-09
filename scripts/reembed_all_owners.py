"""Re-embed SME bios, audience profiles, and messaging docs under the
ACTIVE embedding model.

Companion to ``enrich_and_reembed.py`` (conferences) and
``enrich_pillars.py`` (pillars) for embedding-model rollovers: after the
active row in ``vectors.embedding_models`` changes (e.g. migration
20260705_1000_embed_v2moe), chunks embedded under the old model are
invisible to the matcher until each owner is re-embedded. This script
walks every active SME / audience / messaging doc and calls
``embed_owner`` with the same text each service composes on save, so
the stored chunks are byte-identical to what a fresh save would produce.

Idempotent — ``embed_owner`` replaces the owner's chunks under the
active model. Safe to re-run.

Run from inside the api container::

    podman cp scripts/reembed_all_owners.py scout-api:/tmp/reembed_all_owners.py
    podman exec -e PYTHONPATH=/app scout-api python /tmp/reembed_all_owners.py
"""

from __future__ import annotations

import asyncio
import sys
import time

from sqlalchemy import select

from app.db.models.entities import AudienceProfile, MessagingDocument, Sme
from app.db.session import get_session_factory
from app.services.audience_service import _audience_embed_text
from app.services.embeddings import embed_owner
from app.services.messaging_service import _messaging_embed_text


async def _reembed(owner_type: str, owner_id, text: str) -> bool:
    """One owner per session; commit independently so ctrl-C keeps progress."""
    if not text or not text.strip():
        print(f"  skip {owner_type} {owner_id}: empty text")
        return False
    factory = get_session_factory()
    async with factory() as db:
        try:
            n = await embed_owner(
                db,
                owner_type=owner_type,
                owner_id=owner_id,
                text=text,
                purpose=f"reembed:{owner_type}",
            )
            await db.commit()
            print(f"  ok   {owner_type} {owner_id}: {n} chunks")
            return True
        except Exception as exc:  # noqa: BLE001 — report and continue
            await db.rollback()
            print(f"  FAIL {owner_type} {owner_id}: {type(exc).__name__}: {exc}")
            return False


async def main() -> int:
    started = time.perf_counter()
    factory = get_session_factory()
    async with factory() as db:
        smes = list(
            (await db.execute(select(Sme).where(Sme.is_active.is_(True)))).scalars()
        )
        audiences = list(
            (
                await db.execute(
                    select(AudienceProfile).where(AudienceProfile.is_active.is_(True))
                )
            ).scalars()
        )
        docs = list(
            (
                await db.execute(
                    select(MessagingDocument).where(MessagingDocument.is_active.is_(True))
                )
            ).scalars()
        )

    work = (
        [("sme_bio", s.id, s.bio) for s in smes]
        + [("audience", a.id, _audience_embed_text(a)) for a in audiences]
        + [("messaging", m.id, _messaging_embed_text(m)) for m in docs]
    )
    print(f"re-embedding {len(smes)} smes, {len(audiences)} audiences, {len(docs)} messaging docs")

    ok = 0
    for owner_type, owner_id, text in work:
        ok += await _reembed(owner_type, owner_id, text)

    elapsed = time.perf_counter() - started
    print(f"done: {ok}/{len(work)} succeeded in {elapsed:.0f}s")
    return 0 if ok == len(work) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
