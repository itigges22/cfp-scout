"""Every mapped model must be reachable from app.db.models.

WHY THIS EXISTS
    ``alembic revision --autogenerate`` compares the model metadata against
    the live database and proposes dropping anything the metadata does not
    know about. Two ways that goes wrong, and this codebase has hit both:

      1. A model class exists but is never imported into
         ``app/db/models.py``. It is then absent from the
         metadata unless some other module happens to import it, so
         autogenerate proposes DROP TABLE. ``AppSettingOverride`` survived
         only incidentally, because ``ops`` was imported for its siblings.

      2. A CHECK constraint exists in the database but is not declared in
         the model's ``__table_args__``. Autogenerate proposes dropping the
         constraint. ``talk_submissions_outcome_check`` was in this state.

    Neither fails loudly. The damage arrives later, inside an unrelated
    migration someone generated for a different reason — which is the worst
    possible time to discover it.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

MODELS = pathlib.Path(__file__).resolve().parents[2] / "app" / "db" / "models"


def _declared_model_classes() -> dict[str, str]:
    """``{ClassName: module_stem}`` for every mapped model in the package."""
    found: dict[str, str] = {}
    for path in MODELS.glob("*.py"):
        if path.name == "__init__.py":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ClassDef) and any(
                isinstance(b, ast.Name) and b.id == "Base" for b in node.bases
            ):
                found[node.name] = path.stem
    return found


def test_every_model_is_imported_into_the_package_init() -> None:
    """Absent from __init__ means absent from the metadata, which means
    autogenerate proposes dropping the table."""
    from app.db import models as pkg

    missing = [
        name for name in _declared_model_classes() if not hasattr(pkg, name)
    ]
    assert not missing, (
        f"models not importable from app.db.models: {sorted(missing)}. "
        "Add them to the import block — otherwise the next unrelated "
        "`alembic revision --autogenerate` proposes DROP TABLE for them."
    )


def test_every_model_is_in_all() -> None:
    from app.db import models as pkg

    declared = set(_declared_model_classes())
    exported = set(pkg.__all__)
    missing = declared - exported
    assert not missing, f"models missing from __all__: {sorted(missing)}"


#: NOTE ck_conferences_event_kind_allowed is deliberately absent: event
#: kinds became an operator setting (20260727_2200), and a DDL constraint
#: frozen at migration time cannot enforce a list edited at runtime.
#: Validation for that field lives in ConferenceCreate/ConferenceUpdate.
#:
#: Names as they exist in Postgres. Note these are the CONVENTION-APPLIED
#: names — alembic/env.py prefixes ``ck_%(table_name)s_``, and it does so
#: both when a migration creates the constraint and when the model
#: declares it. Asserting the bare name here would fail against a model
#: that is in fact correct, which is how the first version of this test
#: reported four false positives.
@pytest.mark.parametrize(
    ("table", "constraint"),
    [
        ("conferences", "ck_conferences_attendance_verdict_allowed"),
        ("participation", "ck_participation_activity_allowed"),
        ("participation", "ck_participation_outcome_allowed"),
        ("matches", "ck_matches_judge_verdict_allowed"),
        ("talk_submissions", "ck_talk_submissions_talk_submissions_outcome_check"),
    ],
)
def test_check_constraints_are_declared_on_the_model(
    table: str, constraint: str
) -> None:
    """Each of these exists in the database. If the model does not also
    declare it, autogenerate proposes dropping it.

    Asserted against the mapped metadata rather than by reading source, so
    a constraint that is declared but misnamed still fails.
    """
    from app.db.models import Base

    target = next(
        (t for t in Base.metadata.tables.values() if t.name == table), None
    )
    assert target is not None, f"no mapped table named {table}"

    names = {c.name for c in target.constraints if c.name}
    assert constraint in names, (
        f"{table} is missing CHECK {constraint!r} in __table_args__. "
        f"It exists in the database, so autogenerate will propose DROPPING "
        f"it during the next unrelated migration. Declared: {sorted(names)}"
    )
