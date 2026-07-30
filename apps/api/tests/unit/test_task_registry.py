"""Services queue work by NAME; the names have to resolve.

Six services used to import app.tasks directly to enqueue follow-up work.
That is backwards — a service should not know about the job layer that
schedules it — and it was half of the `scheduler -> tasks -> services ->
scheduler` cycle that a dozen deferred imports were hiding.

They now pass a string. The cost of that trade is that a typo fails at call
time instead of import time, which is exactly what these tests buy back.
"""

from __future__ import annotations

import ast
import pathlib

import pytest
from app.jobs import ENQUEUEABLE

SERVICES = pathlib.Path(__file__).resolve().parents[2] / "app/services"


def _names_enqueued_in_services() -> set[str]:
    """Every string literal passed as the first arg to enqueue_task()."""
    found: set[str] = set()
    for path in SERVICES.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for n in ast.walk(tree):
            if (
                isinstance(n, ast.Call)
                and getattr(n.func, "id", None) == "enqueue_task"
                and n.args
                and isinstance(n.args[0], ast.Constant)
                and isinstance(n.args[0].value, str)
            ):
                found.add(n.args[0].value)
    return found


def test_every_name_a_service_queues_is_registered() -> None:
    """The whole point. A name that is not in ENQUEUEABLE is a KeyError in
    production, at whatever hour the code path first runs."""
    used = _names_enqueued_in_services()
    assert used, "no enqueue_task() calls found — did the helper get renamed?"
    unknown = used - set(ENQUEUEABLE)
    assert not unknown, (
        f"services queue {sorted(unknown)}, which app/scheduler.py does not "
        f"register. Known: {sorted(ENQUEUEABLE)}"
    )


def test_no_service_imports_the_task_layer() -> None:
    """The inversion, banned. This is what the registry exists to prevent."""
    offenders: list[str] = []
    for path in SERVICES.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("app.tasks"):
                offenders.append(f"{path.relative_to(SERVICES)} -> {n.module}")
    assert not offenders, (
        f"services importing the task layer: {offenders}. Queue by name with "
        f"enqueue_task() instead."
    )


def test_an_unregistered_name_fails_loudly() -> None:
    from app.scheduler import enqueue_task

    with pytest.raises(KeyError, match="no-such-task"):
        enqueue_task("no-such-task")


def test_registration_covers_every_declared_task() -> None:
    """ENQUEUEABLE must map to real callables, not stale references."""
    for name, func in ENQUEUEABLE.items():
        assert callable(func), f"{name} is not callable"
