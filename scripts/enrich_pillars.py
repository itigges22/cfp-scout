"""One-shot: enrich each strategic pillar from the active messaging corpus.

Iterates the (small) set of pillars sequentially — 4 LLM calls total
on a typical install — and persists each result to
``app.strategic_pillars.enriched_description``. Safe to re-run; later
runs overwrite earlier ones.

Run inside the api container::

    podman cp scripts/enrich_pillars.py scout-api:/tmp/enrich_pillars.py
    podman exec scout-api /app/.venv/bin/python /tmp/enrich_pillars.py
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select, update

from app.db.models.entities import StrategicPillar
from app.db.session import get_session_factory
from app.services import settings_overrides
from app.services.pillar_enrichment import _load_messaging_corpus, enrich_pillar
from app.settings import get_settings

FORCE = "--force" in sys.argv


async def _bootstrap_settings() -> None:
    factory = get_session_factory()
    async with factory() as s:
        await settings_overrides.load_from_db(s)
    get_settings.cache_clear()


async def main() -> int:
    await _bootstrap_settings()
    s = get_settings()
    print(
        f"LLM dry_run={s.llm_dry_run} chat={s.llm_chat_model} model={s.llm_chat_model}"
    )

    factory = get_session_factory()
    async with factory() as db:
        # Single corpus load — shared across all 4 pillar calls.
        corpus = await _load_messaging_corpus(db)
        print(f"Loaded {len(corpus)} messaging documents:")
        for title, text in corpus:
            print(f"  · {title}: {len(text)} chars")
        if not corpus:
            print("ERROR: no active messaging documents with content. Aborting.")
            return 1

        pillars = (
            await db.execute(select(StrategicPillar).order_by(StrategicPillar.display_order))
        ).scalars().all()
        print(f"\nEnriching {len(pillars)} pillars...")

        for p in pillars:
            if p.enriched_description and not FORCE:
                print(f"  SKIP {p.name} (already enriched — pass --force to redo)")
                continue
            print(f"  · {p.name} ...", end=" ", flush=True)
            text = await enrich_pillar(db=db, pillar=p, corpus=corpus)
            if text is None:
                print("FAILED (LLM returned nothing or errored)")
                continue
            await db.execute(
                update(StrategicPillar)
                .where(StrategicPillar.id == p.id)
                .values(enriched_description=text)
            )
            await db.commit()
            print(f"OK ({len(text)} chars, {len(text.split())} words)")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
