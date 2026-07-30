"""Regenerate tests/fixtures/corpus_vectors.json. Run by hand, not in CI.

WHY THIS EXISTS
    The ranking harness (tests/unit/test_ranking_quality.py) needs real
    embeddings — the whole point is to measure what the shipped scorer
    does, and a synthetic vector measures nothing. But a test that calls
    an LLM cannot live in the suite: it needs a key, it costs money, and
    it turns a unit test into a network dependency.

    So the vectors are computed ONCE, here, against the real embedding
    model, and committed. The harness then reads them and never touches
    the network.

WHEN TO RE-RUN
    * the corpus text changes
    * settings.llm_embedding_model changes — vectors from one model are
      not comparable with another's, and the harness will refuse to run
      if the recorded model name no longer matches

HOW
    Needs a working LLM configuration (base URL + key), the same one the
    app uses:

        uv run python -m tests.fixtures.build_corpus_vectors

    The output file contains ONLY vectors and the model name. No
    credentials, no prompts, nothing that should not be in a repository.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import pathlib

from tests.fixtures import corpus

OUT = pathlib.Path(__file__).parent / "corpus_vectors.json"

#: Round to 6 decimals. nomic vectors carry far more precision than
#: cosine similarity needs at 2-decimal comparison, and full float64
#: repr triples the file size for no measurable difference.
_PRECISION = 6


def text_key(text: str) -> str:
    """Stable id for a piece of corpus text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def corpus_texts() -> list[str]:
    """Every string the harness will need embedded.

    Kept in one place so the builder and the harness cannot disagree
    about what gets embedded — a mismatch would show up as a confusing
    KeyError at test time rather than as "you need to rebuild".
    """
    texts: list[str] = []
    for p in corpus.PILLARS:
        texts.append(f"{p['name']}: {p['description']}")
    for m in corpus.MESSAGING:
        texts.append(m["elevator_pitch"])
    for s in corpus.SMES:
        texts.append(s["bio"])
    for t in corpus.TALKS:
        texts.append(f"{t['title']}. {t['abstract']}")
    for c in corpus.CONFERENCES:
        texts.append(conference_text(c))
    # De-duplicate but keep order stable for a readable diff.
    seen: set[str] = set()
    out: list[str] = []
    for t in texts:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def conference_text(c: dict) -> str:
    """Mirror of services/conference_text.conference_embed_text.

    Deliberately a copy rather than an import: the corpus holds plain
    dicts, not Conference rows. If the real function changes shape, this
    should be updated to match — the harness measures the shipped
    scorer, so drifting here would quietly measure something else.
    """
    parts = [c["name"], c["description"]]
    if c.get("cfp_topics"):
        parts.append("CFP topics: " + ", ".join(c["cfp_topics"]))
    loc = " / ".join(x for x in (c.get("location_city"), c.get("location_country")) if x)
    if loc:
        parts.append(f"Location: {loc}")
    return "\n".join(parts)


async def main() -> None:
    from app.db.session import get_session_factory
    from app.services.llm import EmbeddingRequest, get_llm_client
    from app.settings import get_settings

    settings = get_settings()
    model = settings.llm_embedding_model
    texts = corpus_texts()
    print(f"embedding {len(texts)} corpus texts with {model} ...")

    client = get_llm_client()
    vectors: dict[str, list[float]] = {}
    async with get_session_factory()() as db:
        # Batched: one call per 32 texts keeps each request well inside
        # the model's context and makes a partial failure cheap to retry.
        for i in range(0, len(texts), 32):
            batch = texts[i : i + 32]
            resp = await client.embed(
                EmbeddingRequest(texts=batch, purpose="corpus_fixture"), db=db
            )
            for text, vec in zip(batch, resp.vectors, strict=True):
                vectors[text_key(text)] = [round(float(x), _PRECISION) for x in vec]
            print(f"  {min(i + 32, len(texts))}/{len(texts)}")
        await db.commit()

    OUT.write_text(
        json.dumps({"model": model, "vectors": vectors}, indent=0, sort_keys=True)
    )
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB, {len(vectors)} vectors)")


if __name__ == "__main__":
    asyncio.run(main())
