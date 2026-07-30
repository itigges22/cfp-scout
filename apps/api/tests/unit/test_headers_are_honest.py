"""Module headers must not describe code that no longer exists.

Every module here carries a WHAT THIS DOES / HOW IT CONNECTS header, and a
reader reaches for it before the code. That makes a stale one worse than no
header at all — it is confidently wrong.

They have drifted repeatedly: after deletions, headers still named
`matcher/lexical.py`, `services/workbook/`, `api/v1/config.py`, a graph cache
and a four-stage matcher, none of which exist. One pair actively
contradicted each other about which HTTP header carries the signed-in user.

This checks the mechanical half — that a header does not name a module,
setting or symbol the repo does not have. It cannot check whether prose is
true, so it is a floor, not a guarantee.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

APP = pathlib.Path(__file__).resolve().parents[2] / "app"
PY_FILES = sorted(APP.rglob("*.py"))

#: Things deleted during the restructure. A header naming one is stale by
#: definition. Kept explicit rather than inferred, so the failure message
#: says what happened rather than just "not found".
REMOVED = {
    "matcher/lexical.py": "the lexical co-signal (S8)",
    "services/workbook": "the XLSX round-trip (P2)",
    "services/graph": "the knowledge graph (P1)",
    "api/v1/config.py": "the workbook router (P2)",
    "api/v1/graph.py": "the graph router (P1)",
    "api/v1/versions.py": "the versioning router (P3)",
    "lifecycle/versioning.py": "content versioning (P3)",
    "matcher/_continents.py": "merged into services/geography.py",
    "past_conferences": "collapsed into participation (S4)",
}


def _header(path: pathlib.Path) -> str:
    try:
        doc = ast.get_docstring(ast.parse(path.read_text()))
    except SyntaxError:
        return ""
    return doc or ""


@pytest.mark.parametrize("path", PY_FILES, ids=lambda p: str(p.name))
def test_no_header_names_a_deleted_module(path: pathlib.Path) -> None:
    header = _header(path)
    if not header:
        return
    hits = [
        f"{name} ({why})"
        for name, why in REMOVED.items()
        if name in header
        # a header may narrate its own history, e.g. "X was removed because"
        and not re.search(
            rf"{re.escape(name)}[^.]*\b(removed|deleted|used to|no longer|"
            rf"replaced|superseded|until)\b",
            header,
        )
        and not re.search(
            rf"\b(removed|deleted|used to|no longer|replaced|superseded|"
            rf"which is gone|is gone)\b[^.]*{re.escape(name)}",
            header,
        )
    ]
    assert not hits, f"{path.relative_to(APP)} header names {hits}"


@pytest.mark.parametrize("path", PY_FILES, ids=lambda p: str(p.name))
def test_no_header_tunes_on_a_setting_that_does_not_exist(
    path: pathlib.Path,
) -> None:
    """`Tuning settings.X` naming a removed field sends a reader hunting."""
    from app.settings import Settings

    header = _header(path)
    # Three legitimate forms are not field references:
    #   settings.py / settings.tsx   a filename
    #   settings.llm_*               a wildcard over a family
    #   get_settings.cache_clear()   a method on the accessor
    named = {
        m
        for m in re.findall(r"settings\.([a-z_][a-z0-9_]*)\*?", header)
        if m not in {"py", "tsx", "ts", "json", "yaml", "yml", "md", "cache_clear"}
        and f"settings.{m}*" not in header
    }
    unknown = {
        n
        for n in named
        if n not in Settings.model_fields and not hasattr(Settings, n)
    }
    assert not unknown, (
        f"{path.relative_to(APP)} header references settings.{unknown} — "
        f"no such field"
    )


def test_the_stage_vocabulary_is_gone() -> None:
    """The matcher has two signals and a veto, not four weighted stages.

    Fifteen modules still described the old design after it was replaced,
    including the model file listing per-stage score columns that no longer
    existed — contradicting its own updated Tuning line two paragraphs down.
    """
    offenders = [
        str(p.relative_to(APP))
        for p in PY_FILES
        if re.search(r"\bStage [A-D]\b|four[- ]stage|four matcher stages", _header(p))
    ]
    assert not offenders, f"stage vocabulary survives in {offenders}"
