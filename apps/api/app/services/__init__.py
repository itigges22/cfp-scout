"""Business-logic services.

Routes do parameter parsing + response shaping; services do the actual work
(DB queries, FK checks, audit-log writes, embedding regeneration enqueue,
etc.).

Each entity gets one module here. See ``PLANS/phase-1/09-manual-data-entry.md``
for the design.
"""
