"""No scheduled job may overwrite a conference's status.

WHY THIS EXISTS
    A nightly decay pass ran this against the whole table:

        UPDATE app.conferences SET status='archived'
        WHERE end_date < now() - 90 days
          AND status NOT IN ('archived','quarantined')

    ``conferences.status`` is where the operator's approve/reject decision
    is persisted (api/v1/conferences/decisions.py). So ninety days after
    an event finished, a cron rewrote `approved` to `archived` — on
    exactly the conferences the team had attended, the anchor rows for the
    whole attended half of the data model. It left no audit row, unlike
    every other status write in the codebase.

    ``archived`` had also never been added to the vocabulary in
    services/conferences/conference_status.py, so those rows were not in
    HIDDEN_FROM_FINDER (still visible) and fell outside SCOREABLE
    (silently unscoreable) — precisely the drift that module exists to
    prevent.

    The whole job is now deleted; migration 20260727_1400 restored the
    statuses it overwrote from app.decisions. This test guards the rule
    that outlives it: a status change is a decision, decisions get audit
    rows, and background jobs do not make them.

    "Has this event finished?" is ``end_date < today``. A question, not a
    state to store.
"""

from __future__ import annotations

import ast
import pathlib

from app.settings import get_settings

APP = pathlib.Path(__file__).resolve().parents[2] / "app"
TASKS = APP / "tasks"


def _writes_status(src: str) -> bool:
    """True if the module writes a CONFERENCE status.

    Scoped to modules that reference Conference. tasks.py sets
    ``job.status`` on every IngestJob row it runs — that is job
    bookkeeping, not a decision about an event, and flagging it would
    make this guard noise.
    """
    tree = ast.parse(src)
    if "Conference" not in {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}:
        return False
    for node in ast.walk(tree):
        targets = (
            [node.target] if isinstance(node, ast.AnnAssign) else getattr(node, "targets", [])
        )
        if any(isinstance(t, ast.Attribute) and t.attr == "status" for t in targets):
            return True
        # Core bulk UPDATE with .values(status=...) — the shape the decay
        # pass used, which no attribute check would ever have caught.
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "values"
            and any(kw.arg == "status" for kw in node.keywords)
        ):
            return True
    return False


def test_no_scheduled_task_writes_conference_status() -> None:
    offenders = [
        str(p.relative_to(APP))
        for p in TASKS.rglob("*.py")
        if _writes_status(p.read_text())
    ]
    assert not offenders, (
        f"background tasks writing a status: {sorted(offenders)}. "
        "conferences.status holds the operator's decision — changing it is "
        "a decision, and decisions need an audit row. If a job needs to "
        "express 'this event has finished', derive it from end_date instead."
    )


def test_archived_never_returns_as_a_conference_status() -> None:
    """It was never a declared status. If past-ness ever does need to be
    one, it has to be added to ALL first so every derived set classifies
    it — that is the whole point of the vocabulary module."""
    from app.services import conferences as cs

    assert "archived" not in cs.ALL

    offenders = []
    for path in APP.rglob("*.py"):
        src = path.read_text()
        tree = ast.parse(src)
        # Scope to conference-handling modules: ChatSession has an
        # unrelated `archived` boolean and api/v1/agent.py uses the word
        # as a response key. A guard that cries wolf gets deleted.
        if "Conference" not in {
            n.id for n in ast.walk(tree) if isinstance(n, ast.Name)
        }:
            continue
        if any(
            isinstance(n, ast.Constant) and n.value == "archived"
            for n in ast.walk(tree)
        ):
            offenders.append(str(path.relative_to(APP)))
    assert not offenders, (
        f"'archived' is back in conference code: {sorted(set(offenders))}"
    )


def test_the_decay_job_is_gone_entirely() -> None:
    """Once the archive step went, the pass did one thing: recompute a
    conferences.freshness_score that was read by a single line of display
    code and one diagnostics chart. Nothing ranked or filtered on it, and
    it measured `updated_at` — when someone last edited the row — not
    whether the event mattered."""
    assert not (APP / "services" / "lifecycle").exists()
    assert not (APP / "tasks" / "run_decay_pass.py").exists()

    jobs = (APP / "jobs.py").read_text()
    assert "decay_pass" not in jobs, "the decay cron is still registered"


def test_chunk_decay_survived_and_lives_beside_its_caller() -> None:
    """Chunk-level decay is a different thing and stays: it uses each
    chunk's own last_used_at/created_at and genuinely tilts ranking.

    It now sits in services/matcher.py next to apply_chunk_decay, its only
    caller — which also removed the import cycle the old package needed a
    lazy import to dodge."""
    from app.services.matcher import (
        apply_chunk_decay,
        apply_decay_multiplier,
        compute_freshness,
    )

    assert get_settings().chunk_half_life_days == 60
    assert compute_freshness(reference_time=None, half_life_days=60) == 1.0
    assert apply_decay_multiplier(1.0, 0.0) == 0.85
    assert callable(apply_chunk_decay)

    src = (APP / "services" / "matcher.py").read_text()
    assert "Lazy import" not in src, "the cycle is gone; the workaround should be too"
