"""There is one answer to "what is this conference's overall score".

There were three. The list recomputed it live from the stored signals plus
current boosts; the detail page and the dashboard read the persisted
`matches.overall_score` from whenever the matcher last ran. The same
conference showed two different numbers on two screens — the exact complaint
that started the scoring redesign, arriving by a different route.
"""

from __future__ import annotations

import ast
import pathlib

#: The conference surface was a package (P6) and is one module again —
#: the sibling files it guarded against no longer exist to hide in. The
#: check still matters: one file can hold two formulas just as easily.
CONF_PKG = pathlib.Path(__file__).resolve().parents[2] / "app/api/v1/conferences.py"
CONF_SOURCES = [CONF_PKG]


def _calls_named(name: str) -> int:
    total = 0
    for path in CONF_SOURCES:
        tree = ast.parse(path.read_text())
        total += sum(
            1
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and (
                getattr(n.func, "id", None) == name
                or getattr(n.func, "attr", None) == name
            )
        )
    return total


def test_every_score_consumer_goes_through_the_shared_definition() -> None:
    """The list, the detail page and the dashboard card, all three."""
    assert _calls_named("live_overall_score") >= 3, (
        "a consumer is computing the overall score its own way again"
    )


def test_the_router_does_not_blend_signals_itself() -> None:
    """Calling blend() directly skips the boosts and reproduces the split."""
    assert _calls_named("blend") == 0, (
        "the conferences package calls blend() directly — use live_overall_score so "
        "the boosts are included"
    )


def test_the_default_list_query_has_a_deterministic_order() -> None:
    """assign_ranks preserves input order inside a tie group.

    With no ORDER BY, Postgres may return tied conferences differently on
    each request: pagination drops and repeats rows, and ties reshuffle on
    refresh. There WAS no ORDER BY, under a comment claiming there was.
    """
    src = CONF_PKG.read_text()
    marker = 'sort == "score"'
    assert marker in src
    tail = src[src.index(marker) : src.index(marker) + 1400]
    assert "order_by" in tail, "the score path has no deterministic ORDER BY"
    assert "Conference.id" in tail, (
        "the tiebreak is not total — only id is guaranteed unique"
    )
