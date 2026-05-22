"""Background-task entry points (plan 13).

Functions here are registered with the in-process APScheduler. Each one:
  * accepts only JSON-serialisable kwargs (APScheduler pickles them into the
    persistent jobstore)
  * opens its own DB session via ``app.db.session.get_session`` — there is no
    FastAPI request context inside a scheduled run
  * lands one row in ``app.ingest_jobs`` per run for observability (plan 26's
    ``/diagnostics`` page will surface these)

Plan-by-plan filling-in:
  13 (this plan): heartbeat (sanity check), embed_owner_task (async embed)
  14: scrape_source, parse_raw_page
  17: run_fit_match, recompute_all_matches
  19: compute_sme_fit_narrative
  23: link_conference_series
  24: build_cfp_digest
  25: run_decay_pass, reindex_embeddings
"""
