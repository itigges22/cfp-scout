"""The business-logic layer — where the actual work happens.

WHAT THIS DOES
    Marks the services package. The split it enforces: HTTP routes under
    api/v1/ parse parameters and shape responses, and nothing else. Every
    database query, foreign-key check, audit-log write, and embedding
    enqueue lives in a module here.

    Modules directly in this directory are one-per-entity CRUD services
    (talks, SMEs, topics, sources, pillars, messaging documents, audience
    profiles, past conferences) plus a few standalone jobs (enrichment,
    geocoding, settings overrides). Larger subsystems get their own
    subpackage — matcher/, extraction/, scraper/, embeddings/, brief/,
    digest/, agent/ and the rest.

WORTH KNOWING
    Keep this file empty of imports. Several services import each other,
    and pulling them in at package level creates import cycles.
"""
