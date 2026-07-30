"""similar_chunks must report HOW close, not just the order.

It used to return bare ORM rows while two consumers read
`getattr(chunk, "__cosine_similarity__", 0.0)` — an attribute nothing set.
Every hit scored 0.0, so the agent's cross-owner-type merge sorted by a
constant and the brief chose its "most relevant" documents by dict order.
Nothing raised; the output just quietly meant nothing.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_hits_carry_a_real_similarity(test_engine, clean_db) -> None:
    """Insert a chunk holding the query's OWN vector; it must score ~1.0.

    Deterministic without assuming anything about the embedder: the same
    text embedded twice is the same point, so cosine similarity to itself
    is 1. A hit that reports 0.0 for its own vector means the value is not
    being computed at all — which is precisely what used to happen.
    """
    from app.services.embeddings import get_active_embedding_model, similar_chunks
    from app.services.llm import EmbeddingRequest, get_llm_client
    from sqlalchemy.ext.asyncio import async_sessionmaker

    Session = async_sessionmaker(test_engine, expire_on_commit=False)
    async with Session() as db:
        try:
            model = await get_active_embedding_model(db)
            resp = await get_llm_client().embed(
                EmbeddingRequest(texts=["the exact query text"], purpose="test"),
                db=db,
            )
        except Exception as exc:  # no model row, or no LLM reachable
            pytest.skip(f"embedding unavailable in this fixture: {exc}")

        vec = resp.vectors[0]
        owner = uuid.uuid4()
        await db.execute(
            text(
                "INSERT INTO vectors.document_chunks "
                "(id, owner_type, owner_id, chunk_index, text, token_count, "
                " embedding, embedding_model_id) "
                "VALUES (:id,'messaging',:o,0,:t,10,:e,:m)"
            ),
            {
                "id": str(uuid.uuid4()), "o": str(owner), "t": "the exact query text",
                "e": str(list(vec)), "m": str(model.id),
            },
        )
        await db.commit()

        hits = await similar_chunks(
            db, query="the exact query text", k=1, bump_last_used=False
        )
        assert hits, "no hits returned"
        assert 0.0 <= hits[0].similarity <= 1.0
        assert hits[0].similarity > 0.9, (
            f"a chunk holding the query's own vector scored "
            f"{hits[0].similarity} — the similarity is not being computed"
        )


@pytest.mark.asyncio
async def test_hits_come_back_closest_first(test_engine, clean_db) -> None:
    from app.services.embeddings import get_active_embedding_model, similar_chunks
    from app.services.llm import EmbeddingRequest, get_llm_client
    from sqlalchemy.ext.asyncio import async_sessionmaker

    Session = async_sessionmaker(test_engine, expire_on_commit=False)
    async with Session() as db:
        try:
            model = await get_active_embedding_model(db)
            resp = await get_llm_client().embed(
                EmbeddingRequest(
                    texts=["kubernetes platform engineering", "victorian poetry"],
                    purpose="test",
                ),
                db=db,
            )
        except Exception as exc:
            pytest.skip(f"embedding unavailable in this fixture: {exc}")

        for i, vec in enumerate(resp.vectors):
            await db.execute(
                text(
                    "INSERT INTO vectors.document_chunks "
                    "(id, owner_type, owner_id, chunk_index, text, token_count, "
                    " embedding, embedding_model_id) "
                    "VALUES (:id,'messaging',:o,:i,:t,10,:e,:m)"
                ),
                {
                    "id": str(uuid.uuid4()), "o": str(uuid.uuid4()), "i": i,
                    "t": f"doc {i}", "e": str(list(vec)), "m": str(model.id),
                },
            )
        await db.commit()

        hits = await similar_chunks(
            db, query="kubernetes platform engineering", k=2, bump_last_used=False
        )
        assert len(hits) == 2
        sims = [h.similarity for h in hits]
        assert sims == sorted(sims, reverse=True), f"not closest-first: {sims}"
        assert sims[0] > sims[1], "the two documents scored identically"


def test_the_similarity_is_part_of_the_return_type() -> None:
    """A value you must remember to attach is a contract that gets broken.

    Pinning the shape, so nobody reverts to smuggling it on the ORM row.
    """
    from app.services.embeddings import ChunkHit

    assert ChunkHit._fields == ("chunk", "similarity")


def test_nothing_reads_the_old_magic_attribute() -> None:
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2] / "app"
    # A docstring may mention it as history; a getattr means someone is
    # still relying on it.
    offenders = [
        p
        for p in root.rglob("*.py")
        if "getattr(" in p.read_text() and "__cosine_similarity__" in p.read_text()
        and 'getattr(c, "__cosine_similarity__"' in p.read_text()
    ]
    assert not offenders, f"still reading the unset attribute: {offenders}"
