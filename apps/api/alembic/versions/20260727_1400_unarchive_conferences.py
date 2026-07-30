"""Stop the decay pass overwriting decisions, and restore what it overwrote.

THE BUG
    services/lifecycle/decay.py ran nightly and bulk-updated every
    conference whose end_date was more than 90 days ago:

        UPDATE app.conferences SET status='archived'
        WHERE end_date < now() - 90 days
          AND status NOT IN ('archived','quarantined')

    ``conferences.status`` is also where the operator's approve/reject
    decision is persisted (api/v1/conferences/decisions.py:69). So ninety
    days after an event ended, the job rewrote ``approved`` to
    ``archived`` — including on conferences the team actually attended,
    which are the most valuable rows in the schema and the anchor for the
    whole attended-conference side of the data model.

    It did this as a bulk UPDATE with no audit row, while every other
    status write in the codebase records one.

    Worse, ``archived`` was never added to the status vocabulary in
    services/conference_status.py. So it was not in HIDDEN_FROM_FINDER
    (archived conferences still appeared in the finder) and fell outside
    SCOREABLE (so they silently stopped being scored). The module's own
    docstring names that drift as the exact failure it exists to prevent.

THE REPAIR
    The decision itself was never lost — app.decisions keeps a row per
    action with a timestamp. This restores each archived conference to its
    most recent recorded decision, falling back to 'discovered' for rows
    that never had one (those were archived straight from the extraction
    pipeline's initial status, so 'discovered' is accurate rather than a
    guess).

THE FIX
    decay.py no longer writes status at all. Whether an event is in the
    past is ``end_date < today`` — a question, not a state to store. The
    diagram's PAST_ATTENDED vs UNATTENDED split derives from that plus
    participation rows, neither of which any background job needs to
    mutate.

Revision ID: 20260727_1400
Revises: 20260727_1100
"""

from __future__ import annotations

from alembic import op

revision = "20260727_1400"
down_revision = "20260727_1100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE app.conferences AS c
        SET status = COALESCE(
            (
                SELECT d.decision
                FROM app.decisions AS d
                WHERE d.conference_id = c.id
                ORDER BY d.decided_at DESC
                LIMIT 1
            ),
            'discovered'
        )
        WHERE c.status = 'archived'
        """
    )


def downgrade() -> None:
    # Deliberately not reversible. Re-archiving would mean re-applying the
    # data loss this migration exists to undo, and the information needed
    # to identify exactly which rows had been archived is gone once their
    # real statuses are restored. Leaving them correct is the right
    # outcome in both directions.
    pass
