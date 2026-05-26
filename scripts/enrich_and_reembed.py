"""Backfill ``Conference.enriched_description`` + re-embed everything.

One-shot script. Walks every non-quarantined conference, calls the LLM
to generate a 2-3 sentence factual description (or skips if one already
exists), saves it, then re-embeds the conference so the matcher's
embeddings reflect the richer text.

Concurrency: an asyncio.Semaphore in this script bounds how many
conferences are worked on at the same time. Each task owns its own
DB session. The process-wide LLM semaphore inside
``app.services.llm.client`` further bounds the actual chat/embed calls
under the hood, so we can pick a generous number here without risking
a 429.

Safe to interrupt — each row is committed independently, so partial
progress survives ctrl-C.

Run from inside the api container::

    podman cp scripts/enrich_and_reembed.py scout-api:/tmp/enrich_and_reembed.py
    podman exec scout-api /app/.venv/bin/python /tmp/enrich_and_reembed.py
"""

from __future__ import annotations

import asyncio
import sys
import time

from sqlalchemy import delete, select, update

from app.db.models.entities import Conference
from app.db.models.vectors import DocumentChunk
from app.db.session import get_session_factory
from app.services import settings_overrides
from app.services.embeddings import embed_owner
from app.services.enrichment import enrich_conference
from app.services.extraction.pipeline import _conference_embed_text
from app.settings import get_settings

# Re-enrich + re-embed even rows that already have an enriched_description.
# Pass --force on the CLI to wipe and regenerate from scratch.
FORCE = "--force" in sys.argv

# How many conferences to work on in parallel. The LLM client has its
# own process-wide semaphore (llm_max_concurrent_calls) so this is a
# generous upper bound — we just don't want every row's DB session
# open at once.
CONCURRENCY = 8


async def _bootstrap_settings() -> None:
    """Mimic the FastAPI lifespan hook so DB overrides (real LLM creds,
    dry_run=false, real base_url) take precedence over the placeholder
    env vars baked into the container image."""
    factory = get_session_factory()
    async with factory() as s:
        await settings_overrides.load_from_db(s)
    get_settings.cache_clear()


async def _process_one(
    *,
    conf_id,
    name: str,
    sem: asyncio.Semaphore,
    counters: dict[str, int],
    total: int,
) -> None:
    """Enrich + persist + re-embed a single conference. Owns its session."""
    async with sem:
        factory = get_session_factory()
        # Fresh session — load the conference fresh too so any concurrent
        # writes don't bite us.
        async with factory() as s:
            conf = (
                await s.execute(select(Conference).where(Conference.id == conf_id))
            ).scalar_one_or_none()
            if conf is None:
                counters["failed"] += 1
                return

            # Step 1: enrichment. Skip if already populated and not --force.
            new_desc: str | None = None
            if conf.enriched_description and not FORCE:
                counters["skipped"] += 1
            else:
                new_desc = await enrich_conference(
                    db=s,
                    name=conf.name,
                    topics=list(conf.topics or []),
                    country=conf.location_country,
                    city=conf.location_city,
                    is_virtual=bool(conf.is_virtual),
                )
                if new_desc:
                    await s.execute(
                        update(Conference)
                        .where(Conference.id == conf.id)
                        .values(enriched_description=new_desc)
                    )
                    conf.enriched_description = new_desc
                    counters["enriched"] += 1
                else:
                    counters["llm_failed"] += 1

            # Step 2: re-embed. Drop existing chunk(s) and create fresh
            # using the (possibly newly-enriched) text. We do this even
            # for skipped rows so existing-enriched-but-old-embedding
            # rows still get refreshed.
            await s.execute(
                delete(DocumentChunk).where(
                    DocumentChunk.owner_type == "conference",
                    DocumentChunk.owner_id == conf.id,
                )
            )
            text = _conference_embed_text(conf)
            if text.strip():
                try:
                    await embed_owner(
                        s,
                        owner_type="conference",
                        owner_id=conf.id,
                        text=text,
                        purpose="embed:enrichment_backfill",
                    )
                    counters["reembedded"] += 1
                except Exception as exc:  # noqa: BLE001
                    counters["embed_failed"] += 1
                    print(f"  embed FAILED for {conf.name[:60]}: {exc}")
            await s.commit()

    counters["done"] += 1
    if counters["done"] % 25 == 0:
        elapsed = time.monotonic() - counters["_t0"]
        rate = counters["done"] / max(elapsed, 0.001)
        eta = (total - counters["done"]) / max(rate, 0.001)
        print(
            f"  {counters['done']}/{total} "
            f"enriched={counters['enriched']} skipped={counters['skipped']} "
            f"reemb={counters['reembedded']} llm_fail={counters['llm_failed']} "
            f"emb_fail={counters['embed_failed']} "
            f"({rate:.1f}/s · ETA {eta / 60:.1f}min)"
        )


async def main() -> int:
    await _bootstrap_settings()
    settings = get_settings()
    print(
        f"LLM dry_run={settings.llm_dry_run} "
        f"chat={settings.llm_chat_model} "
        f"embed={settings.llm_embedding_model} "
        f"max_concurrent={settings.llm_max_concurrent_calls}"
    )

    factory = get_session_factory()
    async with factory() as s:
        rows = (
            await s.execute(
                select(Conference.id, Conference.name)
                .where(Conference.status != "quarantined")
                .order_by(Conference.created_at)
            )
        ).all()
    total = len(rows)
    print(f"Found {total} non-quarantined conferences. Concurrency={CONCURRENCY}.")

    sem = asyncio.Semaphore(CONCURRENCY)
    counters: dict[str, int] = {
        "enriched": 0,
        "skipped": 0,
        "reembedded": 0,
        "llm_failed": 0,
        "embed_failed": 0,
        "failed": 0,
        "done": 0,
        "_t0": int(time.monotonic()),
    }
    counters["_t0"] = time.monotonic()  # type: ignore[assignment]
    await asyncio.gather(
        *(
            _process_one(
                conf_id=r.id, name=r.name, sem=sem, counters=counters, total=total
            )
            for r in rows
        )
    )

    elapsed = time.monotonic() - counters["_t0"]
    print(
        f"\nDone in {elapsed / 60:.1f}min. "
        f"enriched={counters['enriched']} skipped={counters['skipped']} "
        f"reembedded={counters['reembedded']} "
        f"llm_failed={counters['llm_failed']} embed_failed={counters['embed_failed']} "
        f"failed={counters['failed']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
