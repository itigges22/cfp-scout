"""Operator command line: ``python -m app.maintenance <command>``.

WHAT THIS DOES
    Long-running repair and backfill jobs an operator runs by hand inside
    the api container. Commands: ``enrich-conferences`` and
    ``enrich-pillars`` regenerate LLM-written descriptions and re-embed;
    ``reembed-owners`` re-embeds SME (subject-matter expert) bios,
    audiences and messaging documents after an embedding-model rollover;
    ``backfill-conference-embeddings`` covers conferences with no chunks at
    all; ``refresh-statuses`` recomputes conference status from stored match
    scores (try ``--dry-run`` first). Each is idempotent and commits
    incrementally, so interrupting one keeps the work already done.

HOW IT CONNECTS
    Called by   a human. Nothing in the running app imports this module;
                docs/ops/runbook.md and the embed-rollover migration point
                operators at it.
    Writes      app.conferences, app.strategic_pillars, app.matches,
                vectors.document_chunks
    Helpers     services/conferences/enrichment.py, services/pillars/pillar_enrichment.py,
                services/embeddings/, services/matcher/,
                services/settings_store/settings_store.py (for the config bootstrap)
    Tuning      the same settings the app uses, database overrides included

WORTH KNOWING
    Operator tooling belongs under ``app/`` because that is what the
    Containerfile copies into the image; a helper in a top-level
    ``scripts/`` directory is absent at runtime and outside ruff's and
    pytest's scope besides.

    No command here reimplements a score formula. ``refresh-statuses`` reads
    the scores the matcher already stored, and anything needing to compute a
    match calls services/matcher.py — one copy of the blend, only.

    argparse is handed ``__doc__``, so this text is also ``--help``.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from collections import Counter
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError

from app.db.models import (
    AudienceProfile,
    Conference,
    DocumentChunk,
    Match,
    MessagingDocument,
    Sme,
    StrategicPillar,
)
from app.db.session import dispose_engine, get_session_factory
from app.services import settings_store
from app.services.conferences import conference_embed_text, enrich_conference
from app.services.embeddings import embed_owner
from app.services.matcher import ALGORITHM_VERSION, choose_status
from app.services.positioning import enrich_pillar, load_messaging_corpus, messaging_embed_text

# Private helpers imported from their owning services so the text these
# commands embed stays byte-identical to what a normal save produces.
# Intra-package, but they are the reason a "re-embed" is faithful rather
# than approximate — do not inline copies of them here.
from app.services.taxonomy import audience_embed_text
from app.settings import get_settings


async def _bootstrap_settings() -> None:
    """Load DB-side settings overrides, as the FastAPI lifespan does.

    Without this the command runs on whatever placeholder env the image
    was built with instead of the operator's real LLM credentials.
    """
    async with get_session_factory()() as db:
        await settings_store.load_from_db(db)
    get_settings.cache_clear()


def _print_llm_context() -> None:
    s = get_settings()
    print(
        f"LLM dry_run={s.llm_dry_run} chat={s.llm_chat_model} "
        f"embed={s.llm_embedding_model} max_concurrent={s.llm_max_concurrent_calls}"
    )


# ---------------------------------------------------------------------------
# enrich-conferences
# ---------------------------------------------------------------------------
async def enrich_conferences(*, force: bool, concurrency: int) -> int:
    """Backfill ``Conference.enriched_description`` and re-embed."""
    await _bootstrap_settings()
    _print_llm_context()

    async with get_session_factory()() as db:
        rows = (
            await db.execute(
                select(Conference.id, Conference.name)
                .where(Conference.status != "quarantined")
                .order_by(Conference.created_at)
            )
        ).all()

    total = len(rows)
    print(f"Found {total} non-quarantined conferences. Concurrency={concurrency}.")
    sem = asyncio.Semaphore(concurrency)
    counters: Counter = Counter()
    t0 = time.monotonic()

    async def _one(conf_id: Any) -> None:
        async with sem, get_session_factory()() as db:
            conf = (
                await db.execute(select(Conference).where(Conference.id == conf_id))
            ).scalar_one_or_none()
            if conf is None:
                counters["failed"] += 1
                return

            if conf.enriched_description and not force:
                counters["skipped"] += 1
            else:
                new_desc = await enrich_conference(
                    db=db,
                    name=conf.name,
                    topics=list(conf.topics or []),
                    country=conf.location_country,
                    city=conf.location_city,
                    is_virtual=bool(conf.is_virtual),
                )
                if new_desc:
                    await db.execute(
                        update(Conference)
                        .where(Conference.id == conf.id)
                        .values(enriched_description=new_desc)
                    )
                    conf.enriched_description = new_desc
                    counters["enriched"] += 1
                else:
                    counters["llm_failed"] += 1

            # NO manual DELETE here. The old script dropped every chunk for
            # the owner regardless of embedding_model_id, which wiped the
            # historical vectors that migration 20260705_1000 deliberately
            # keeps so an embedding-model rollover can be rolled back.
            # embed_owner already replaces the owner's chunks under the
            # ACTIVE model, which is exactly the intended scope.
            text = conference_embed_text(conf)
            if text.strip():
                try:
                    await embed_owner(
                        db,
                        owner_type="conference",
                        owner_id=conf.id,
                        text=text,
                        purpose="embed:enrichment_backfill",
                    )
                    counters["reembedded"] += 1
                except Exception as exc:
                    counters["embed_failed"] += 1
                    print(f"  embed FAILED for {conf.name[:60]}: {exc}")
            await db.commit()

        counters["done"] += 1
        if counters["done"] % 25 == 0:
            elapsed = time.monotonic() - t0
            rate = counters["done"] / max(elapsed, 0.001)
            eta = (total - counters["done"]) / max(rate, 0.001)
            print(
                f"  {counters['done']}/{total} enriched={counters['enriched']} "
                f"skipped={counters['skipped']} reemb={counters['reembedded']} "
                f"llm_fail={counters['llm_failed']} emb_fail={counters['embed_failed']} "
                f"({rate:.1f}/s · ETA {eta / 60:.1f}min)"
            )

    await asyncio.gather(*(_one(r.id) for r in rows))
    print(
        f"\nDone in {(time.monotonic() - t0) / 60:.1f}min. "
        f"enriched={counters['enriched']} skipped={counters['skipped']} "
        f"reembedded={counters['reembedded']} llm_failed={counters['llm_failed']} "
        f"embed_failed={counters['embed_failed']} failed={counters['failed']}"
    )
    return 0


# ---------------------------------------------------------------------------
# enrich-pillars
# ---------------------------------------------------------------------------
async def enrich_pillars(*, force: bool) -> int:
    """Regenerate each pillar's ``enriched_description`` from messaging."""
    await _bootstrap_settings()
    _print_llm_context()

    async with get_session_factory()() as db:
        corpus = await load_messaging_corpus(db)
        print(f"Loaded {len(corpus)} messaging documents:")
        for title, text in corpus:
            print(f"  · {title}: {len(text)} chars")
        if not corpus:
            print("ERROR: no active messaging documents with content. Aborting.")
            return 1

        pillars = (
            await db.execute(
                select(StrategicPillar).order_by(StrategicPillar.display_order)
            )
        ).scalars().all()
        print(f"\nEnriching {len(pillars)} pillars...")

        for p in pillars:
            if p.enriched_description and not force:
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


# ---------------------------------------------------------------------------
# reembed-owners
# ---------------------------------------------------------------------------
async def reembed_owners() -> int:
    """Re-embed SME bios, audience profiles and messaging docs.

    Required after the active row in ``vectors.embedding_models`` changes:
    chunks written under the old model are invisible to the matcher, so
    The fit and speaker signals silently score 0 until
    every owner is re-embedded.
    """
    await _bootstrap_settings()
    started = time.perf_counter()

    async with get_session_factory()() as db:
        smes = list((await db.execute(select(Sme).where(Sme.is_active.is_(True)))).scalars())
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
        + [("audience", a.id, audience_embed_text(a)) for a in audiences]
        + [("messaging", m.id, messaging_embed_text(m)) for m in docs]
    )
    print(
        f"re-embedding {len(smes)} smes, {len(audiences)} audiences, "
        f"{len(docs)} messaging docs"
    )

    ok = 0
    for owner_type, owner_id, text in work:
        if not text or not text.strip():
            print(f"  skip {owner_type} {owner_id}: empty text")
            continue
        async with get_session_factory()() as db:
            try:
                n = await embed_owner(
                    db,
                    owner_type=owner_type,
                    owner_id=owner_id,
                    text=text,
                    purpose=f"reembed:{owner_type}",
                )
                await db.commit()
                ok += 1
                print(f"  ok   {owner_type} {owner_id}: {n} chunks")
            except Exception as exc:
                await db.rollback()
                print(f"  FAIL {owner_type} {owner_id}: {type(exc).__name__}: {exc}")

    print(f"done: {ok}/{len(work)} succeeded in {time.perf_counter() - started:.0f}s")
    return 0 if ok == len(work) else 1


# ---------------------------------------------------------------------------
# backfill-conference-embeddings
# ---------------------------------------------------------------------------
async def backfill_conference_embeddings(*, batch_size: int) -> int:
    """Embed conferences that have no chunks at all. No-op when none."""
    await _bootstrap_settings()

    async with get_session_factory()() as db:
        rows = (
            (
                await db.execute(
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

        ok = fail = 0
        for i, c in enumerate(rows, start=1):
            try:
                blob = conference_embed_text(c)
                if not blob:
                    fail += 1
                    continue
                await embed_owner(
                    db,
                    owner_type="conference",
                    owner_id=c.id,
                    text=blob,
                    purpose="embed:backfill",
                )
                ok += 1
                if i % batch_size == 0:
                    await db.commit()
                    print(f"  committed {i}/{total} (ok={ok} fail={fail})", flush=True)
            except SQLAlchemyError as exc:
                await db.rollback()
                print(f"  rollback at {i}: {exc}", flush=True)
                fail += 1
            except Exception as exc:
                fail += 1
                print(f"  fail {c.name[:60]}: {exc}", flush=True)

        await db.commit()
        print(f"Done. ok={ok} fail={fail}", flush=True)
        return 0 if fail == 0 else 1


# ---------------------------------------------------------------------------
# refresh-statuses
# ---------------------------------------------------------------------------
async def refresh_statuses(*, dry_run: bool) -> int:
    """Recompute every conference's status from its current match scores."""
    await _bootstrap_settings()
    settings = get_settings()

    async with get_session_factory()() as db:
        rows = (
            await db.execute(
                select(
                    Conference.id,
                    Conference.name,
                    Conference.status,
                    Match.fit_score,
                    Match.speaker_score,
                    Match.judge_verdict,
                )
                .join(Match, Match.conference_id == Conference.id)
                .where(Match.algorithm_version == ALGORITHM_VERSION)
                .where(Conference.status != "quarantined")
            )
        ).all()
    print(f"Refreshing status on {len(rows)} matched conferences.")

    before: Counter = Counter()
    after: Counter = Counter()
    transitions: Counter = Counter()
    changes: list[tuple[str, str, str]] = []

    for r in rows:
        new_status = choose_status(
            fit_score=r.fit_score,
            speaker_score=r.speaker_score,
            judge_verdict=r.judge_verdict,
            settings=settings,
        )
        before[r.status] += 1
        after[new_status] += 1
        if new_status != r.status:
            transitions[(r.status, new_status)] += 1
            changes.append((r.name, r.status, new_status))

    # Report BEFORE writing. The old script committed first and printed its
    # "so you can sanity-check them" tables afterwards, which made the
    # review a post-mortem of an irreversible change.
    def fmt(counter: Counter) -> str:
        return "  " + "\n  ".join(
            f"{k:<25} {v:>4}" for k, v in sorted(counter.items(), key=lambda x: -x[1])
        )

    print("\nBefore:")
    print(fmt(before))
    print("\nAfter:")
    print(fmt(after))
    if transitions:
        print(f"\n{sum(transitions.values())} conferences would move:")
        for (old, new), n in sorted(transitions.items(), key=lambda x: -x[1]):
            print(f"  {old} → {new}: {n}")
    if changes:
        print("\nSample of moved conferences (first 20 alphabetically):")
        for name, old, new in sorted(changes, key=lambda x: x[0])[:20]:
            print(f"  {name[:60]:<60}  {old}  →  {new}")

    if dry_run:
        print("\n--dry-run: nothing written.")
        return 0
    if not changes:
        print("\nNo changes to apply.")
        return 0

    async with get_session_factory()() as db:
        for r in rows:
            new_status = choose_status(
                fit_score=r.fit_score,
                speaker_score=r.speaker_score,
                judge_verdict=r.judge_verdict,
                settings=settings,
            )
            if new_status != r.status:
                await db.execute(
                    update(Conference)
                    .where(Conference.id == r.id)
                    .values(status=new_status)
                )
        await db.commit()
    print(f"\nApplied {len(changes)} status changes.")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
async def reparse_pages(*, only_missing_description: bool, limit: int | None) -> int:
    """Re-run extraction over pages already on disk.

    WHY THIS EXISTS
        Conferences created before the description column landed carry no
        ``description``, so conference_embed_text falls back to
        ``enriched_description`` — text an LLM invented from the name. The
        matcher scores that, and the judge reasons about it.

        The real page was never thrown away: services/scraper stores every
        fetch as a RawPage. Re-running extraction over those pages fills in
        the real description with no re-crawl, no politeness cost and no
        risk of the site having changed.

        This matters more than it looks now that discovery ingests broadly
        (W1). Judging hundreds of conferences on invented descriptions is
        vetoing at scale on guesses.

    WHAT IT COSTS
        One LLM extraction per page. ``--only-missing-description`` (the
        default) restricts that to pages whose conference still has none,
        which is the set that actually needs it.
    """
    from sqlalchemy import select

    from app.db.models import Conference, ConferenceSource, RawPage
    from app.services.extraction import parse_raw_page

    await _bootstrap_settings()
    _print_llm_context()

    factory = get_session_factory()
    async with factory() as db:
        stmt = select(RawPage.id).order_by(RawPage.created_at)
        if only_missing_description:
            # Pages whose conference has no real description yet. A page
            # that never produced a conference is included too — it may
            # have failed for a reason since fixed.
            linked = (
                select(ConferenceSource.raw_page_id)
                .join(Conference, Conference.id == ConferenceSource.conference_id)
                .where(Conference.description.is_not(None))
            )
            stmt = stmt.where(RawPage.id.not_in(linked))
        if limit:
            stmt = stmt.limit(limit)
        page_ids = [r for (r,) in (await db.execute(stmt)).all()]

    print(f"Re-parsing {len(page_ids)} stored page(s).")
    filled = failed = 0
    for i, pid in enumerate(page_ids, 1):
        async with factory() as db:
            try:
                result = await parse_raw_page(db, pid)
                await db.commit()
            except Exception as exc:  # one bad page must not stop the run
                failed += 1
                print(f"  [{i}/{len(page_ids)}] {pid} failed: {str(exc)[:90]}")
                continue
        if result.ok:
            filled += 1
        if i % 25 == 0 or i == len(page_ids):
            print(f"  [{i}/{len(page_ids)}] parsed_ok={filled} failed={failed}")

    print(f"Done. {filled} page(s) parsed, {failed} failed.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.maintenance",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser(
        "enrich-conferences",
        help="Backfill Conference.enriched_description and re-embed.",
    )
    p.add_argument("--force", action="store_true", help="Redo already-enriched rows.")
    p.add_argument("--concurrency", type=int, default=8)

    p = sub.add_parser("enrich-pillars", help="Regenerate pillar enriched_description.")
    p.add_argument("--force", action="store_true", help="Redo already-enriched pillars.")

    sub.add_parser(
        "reembed-owners",
        help="Re-embed SME bios, audiences and messaging docs (embedding rollover).",
    )

    p = sub.add_parser(
        "backfill-conference-embeddings",
        help="Embed conferences that have no chunks at all.",
    )
    p.add_argument("--batch-size", type=int, default=25)

    p = sub.add_parser(
        "refresh-statuses", help="Recompute conference status from match scores."
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing.",
    )

    p = sub.add_parser(
        "reparse-pages",
        help="Re-run extraction over stored raw_pages (fills real descriptions).",
    )
    p.add_argument(
        "--all",
        dest="only_missing_description",
        action="store_false",
        default=True,
        help="Re-parse every stored page, not just those whose conference "
        "still has no description. Costs one LLM call per page.",
    )
    p.add_argument("--limit", type=int, default=None, help="Stop after N pages.")

    return parser


async def _dispatch(args: argparse.Namespace) -> int:
    try:
        if args.command == "enrich-conferences":
            return await enrich_conferences(
                force=args.force, concurrency=args.concurrency
            )
        if args.command == "enrich-pillars":
            return await enrich_pillars(force=args.force)
        if args.command == "reembed-owners":
            return await reembed_owners()
        if args.command == "backfill-conference-embeddings":
            return await backfill_conference_embeddings(batch_size=args.batch_size)
        if args.command == "reparse-pages":
            return await reparse_pages(
                only_missing_description=args.only_missing_description,
                limit=args.limit,
            )
        if args.command == "refresh-statuses":
            return await refresh_statuses(dry_run=args.dry_run)
        raise SystemExit(f"unknown command {args.command!r}")
    finally:
        await dispose_engine()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return asyncio.run(_dispatch(args))


if __name__ == "__main__":
    sys.exit(main())
