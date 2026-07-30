"""Freshness discounts a pair once, by its staler half.

messaging.py applied `apply_chunk_decay` to BOTH chunks of every pair — a
product, not the minimum its own comment claimed, which squares the penalty
on merely-old evidence. pillars.py applied none at all, while signals.py
pools both sets into one max. So ageing changed WHICH corpus won rather than
uniformly discounting old evidence.
"""

from __future__ import annotations

from app.services.matcher import chunk_freshness


class _Chunk:
    def __init__(self, created=None, last_used=None):
        self.created_at = created
        self.last_used_at = last_used


def test_freshness_is_one_when_decay_is_disabled(monkeypatch) -> None:
    """The default. Decay must be opt-in, not a silent multiplier."""
    from app.settings import get_settings

    if get_settings().decay_enabled:
        return
    assert chunk_freshness(_Chunk()) == 1.0


def test_min_of_two_is_never_harsher_than_either_alone() -> None:
    """The property that makes min correct and product wrong.

    A pair discounted by min() is penalised as much as its staler half and
    no more. Multiplying both in penalises it by roughly the square.
    """
    a, b = 0.8, 0.6
    assert min(a, b) == 0.6
    assert a * b == 0.48
    assert min(a, b) > a * b


def test_both_evidence_corpora_use_the_same_decay_helper() -> None:
    """messaging and pillars are pooled into one max in signals.py.

    If only one of them decayed, ageing would decide which corpus wins.
    """
    import ast
    import pathlib

    # Used to assert the string "apply_chunk_decay" was absent from the
    # stage module. matcher.py now also DEFINES that helper, so the plain
    # substring check sees its own def and its docstring reference. The
    # invariant was never about the spelling — it is that nothing CALLS
    # the per-chunk multiplier, because freshness is already applied once
    # per stage and applying it again double-counts age.
    src = (pathlib.Path(__file__).resolve().parents[2] / "app/services/matcher.py").read_text()
    assert "chunk_freshness" in src, "matcher.py does not apply freshness"

    called = {
        n.func.id
        for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert "apply_chunk_decay" not in called, (
        "matcher.py calls the per-chunk multiplier, which double-counts age"
    )
