"""A table that live code reads but nothing writes is a silent zero.

WHY THIS EXISTS
    ``services/matcher.py`` joined ``messaging_pillars`` to collect the
    messaging evidence behind each strategic pillar. Nothing in the
    application ever inserted a row: ``MessagingPillar`` had zero
    constructor calls anywhere under ``app/``. The join therefore returned
    nothing on every run, and each pillar was scored against its own
    description embedding alone — the evidence the stage was built around
    never arrived.

    Nothing failed. No error, no empty page, no log line. The scores were
    simply computed over less than they claimed to be, and the elaborate
    ``is_active`` filter guarding the join guarded an empty set.

    That is the failure mode this test exists to catch: not a crash, but
    machinery that appears to work because its inputs are quietly absent.

HOW TO FIX A FAILURE
    Either wire up a writer, or delete the table and the code reading it.
    Do not add the model to the tolerated set below to make this pass —
    the set is meant to shrink.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

APP = pathlib.Path(__file__).resolve().parents[2] / "app"
MODELS = APP / "db" / "models.py"

#: Models known to be read-but-never-written, each with a decision still
#: owed. Tracked in D17. This set may only ever get SMALLER — a new entry
#: means someone shipped another silent zero.
#:
#: conference_audiences   read by services/matcher.py to compute the
#:                        `audience_overlap` dimension, which is therefore
#:                        permanently 0.0 and silently redistributes
#:                        sme_w_audience onto the other dimensions. It is
#:                        also the diagram's "Target Audience of
#:                        Conference", so this is a coverage gap too.
#: (talk_tag_assignments was here. It and talk_tags are now deleted —
#: migration 20260727_2400 — because the assignment junction had no writer,
#: so an operator could create a tag and never put it on a talk.)
TOLERATED_UNWRITTEN = {
    "ConferenceAudience",
}


def _model_names() -> set[str]:
    names: set[str] = set()
    # models/ was a package; it is one module now, so rglob finds nothing.
    for path in [MODELS]:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and any(
                isinstance(b, ast.Name) and b.id == "Base" for b in node.bases
            ):
                names.add(node.name)
    return names


#: Core constructs that write. A model can be persisted without ever
#: being instantiated — ``insert(AppSettingOverride).values(...)`` and
#: ``update(Conference).values(...)`` are writes with no constructor call
#: in sight, and an earlier version of this test reported both as dead.
_WRITE_CONSTRUCTS = {"insert", "update", "delete"}


def _constructed_names() -> set[str]:
    """Model classes written anywhere outside the model definitions.

    Counts both ORM instantiation (``Conference(...)``) and Core
    statements (``insert(Conference)``), because either one means rows
    can exist.
    """
    built: set[str] = set()
    for path in APP.rglob("*.py"):
        if MODELS in path.parents:
            continue
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id in _WRITE_CONSTRUCTS:
                for arg in node.args:
                    if isinstance(arg, ast.Name):
                        built.add(arg.id)
            else:
                built.add(node.func.id)
    return built


def _referenced_names() -> set[str]:
    """Model classes mentioned in service/api code — i.e. something reads them."""
    seen: set[str] = set()
    for sub in ("services", "api", "tasks"):
        for path in (APP / sub).rglob("*.py"):
            try:
                tree = ast.parse(path.read_text())
            except SyntaxError:  # pragma: no cover
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Name):
                    seen.add(node.id)
                elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                    seen.add(node.value.id)
    return seen


def _migration_seeded_names() -> set[str]:
    """Models whose rows come from a migration rather than app code.

    Reference data is a real and legitimate case — ``embedding_models``
    holds the model registry, seeded in 20260521_1210 and extended in
    20260705_1000, and the application only ever reads it. That is not a
    dead table, so it must not be reported as one.

    Verified rather than listed: the table name has to actually appear in
    a migration that inserts. If someone deletes the seed, this stops
    covering the model and the main test starts failing again — which is
    the correct outcome.
    """
    versions = APP.parent / "alembic" / "versions"
    blobs = [p.read_text() for p in versions.rglob("*.py")]

    seeded: set[str] = set()
    for class_name, table_name in _model_tables().items():
        # The table must be the TARGET of an insert, not merely named in a
        # migration that inserts into something else. An earlier version of
        # this checked only that both words appeared in the same file, which
        # the initial baseline satisfies for every table in the schema — so
        # the guard silently exempted everything and could not fail.
        pattern = re.compile(
            rf"insert\s+into\s+[\w.\"]*\b{re.escape(table_name)}\b"
            rf"|bulk_insert\(\s*[\w.]*\b{re.escape(table_name)}\b",
            re.IGNORECASE,
        )
        if any(pattern.search(b) for b in blobs):
            seeded.add(class_name)
    return seeded


def _model_tables() -> dict[str, str]:
    """``{ClassName: __tablename__}`` for every mapped model."""
    out: dict[str, str] = {}
    # models/ was a package; it is one module now, so rglob finds nothing.
    for path in [MODELS]:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.ClassDef)
                and any(isinstance(b, ast.Name) and b.id == "Base" for b in node.bases)
            ):
                continue
            for stmt in node.body:
                targets = (
                    [stmt.target] if isinstance(stmt, ast.AnnAssign) else
                    getattr(stmt, "targets", [])
                )
                if (
                    any(isinstance(t, ast.Name) and t.id == "__tablename__" for t in targets)
                    and isinstance(stmt.value, ast.Constant)
                ):
                    out[node.name] = stmt.value.value
    return out


def test_no_new_table_is_read_but_never_written() -> None:
    models = _model_names()
    constructed = _constructed_names()
    referenced = _referenced_names()

    unwritten = {m for m in models if m in referenced and m not in constructed}
    new = unwritten - TOLERATED_UNWRITTEN - _migration_seeded_names()

    assert not new, (
        "these models are read by live code but nothing ever constructs one, "
        f"so every query over them returns nothing: {sorted(new)}. "
        "Either add a writer or delete the table and its readers — do not "
        "add them to TOLERATED_UNWRITTEN."
    )


@pytest.mark.parametrize("name", sorted(TOLERATED_UNWRITTEN))
def test_the_tolerated_set_does_not_outlive_its_subject(name: str) -> None:
    """Guards the other direction: once one of these is fixed or deleted,
    its entry has to go too, or the set quietly stops meaning anything."""
    models = _model_names()
    constructed = _constructed_names()

    assert name in models, (
        f"{name} is in TOLERATED_UNWRITTEN but no longer exists — remove the entry"
    )
    assert name not in constructed, (
        f"{name} now has a writer — remove it from TOLERATED_UNWRITTEN"
    )


def test_messaging_pillars_is_gone() -> None:
    """The case that prompted this file. pillars.py now joins on the
    scalar messaging_documents.pillar_id, which the app maintains."""
    assert "MessagingPillar" not in _model_names()

    # Check for real usage rather than any mention — the explanation of
    # why the junction went lives in a comment there on purpose, and a
    # test that forbade naming it would delete the reason along with it.
    src = (APP / "services" / "matcher.py").read_text()
    tree = ast.parse(src)
    used = {
        n.id for n in ast.walk(tree) if isinstance(n, ast.Name)
    } | {
        alias.name for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom)
        for alias in n.names
    }
    assert "MessagingPillar" not in used, "pillars.py still uses the deleted junction"
    assert "MessagingDocument.pillar_id" in src
