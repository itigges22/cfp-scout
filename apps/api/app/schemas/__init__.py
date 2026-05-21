"""Pydantic v2 schemas for Scout's user-input data.

These schemas are the single source of truth for **what counts as valid input**
across both the manual-entry UI (plan 09) and the XLSX workbook import
(plan 31). Every schema uses `extra='forbid'` so unknown fields are rejected
loudly, not silently dropped.

See ``PLANS/phase-1/05-data-input-guardrails.md`` for the design rationale
and ``docs/ops/data-guardrails.md`` for an operator-facing reference of
what's rejected and why.
"""
