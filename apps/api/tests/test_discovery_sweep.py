"""The keyword sweep: does three keywords actually become a deep search?

WHY THIS EXISTS
    Discovery used to issue exactly one query and take the first twenty
    results, which is the failure the operator named directly: "it cannot
    find a list of 10 or 20 and then be done." These tests pin the two
    properties that fix carries.

    RECALL IS THE OBJECTIVE. Every assertion here is about not losing
    candidates — the expansion producing more queries than keywords, a
    failing provider costing only its own query, and the union keeping
    everything any query found. A conference the operator never sees is
    invisible forever; noise costs one click to reject.
"""

from __future__ import annotations

import pytest
from app.services import discovery as search_mod
from app.services.discovery import SearchHit, build_queries, web_search_many
from app.settings import SPECS


# --- expansion -------------------------------------------------------------
def test_keywords_expand_into_many_queries():
    """N keywords must not mean N searches, or the sweep is not a sweep."""
    queries = build_queries(
        keywords=["AI", "LLM", "Kubernetes"],
        templates=['{keyword} conference {year} "call for papers"', "{keyword} summit {year}"],
        years=[2026, 2027],
    )
    # 3 keywords x 2 phrasings x 2 years
    assert len(queries) == 12
    assert 'AI conference 2026 "call for papers"' in queries
    assert "Kubernetes summit 2027" in queries


def test_expansion_scales_to_the_operators_stated_upper_bound():
    """The operator said they might enter up to 100 keywords."""
    queries = build_queries(
        keywords=[f"kw{i}" for i in range(100)],
        templates=["{keyword} conference {year}", "{keyword} summit {year}"],
        years=[2026, 2027],
    )
    assert len(queries) == 400
    # Distinctness matters: duplicate queries are wasted provider calls.
    assert len(set(queries)) == len(queries)


def test_duplicate_queries_are_collapsed():
    """Two keywords differing only in whitespace/case of the same word
    should not buy two identical provider calls."""
    queries = build_queries(
        keywords=["AI", " AI "],
        templates=["{keyword} conference {year}"],
        years=[2026],
    )
    assert queries == ["AI conference 2026"]


def test_template_without_placeholders_is_used_once_not_per_keyword():
    """An operator adding a standalone query should get exactly that,
    not the same string repeated once per keyword."""
    queries = build_queries(
        keywords=["AI", "LLM", "MLOps"],
        templates=["devops conference amsterdam"],
        years=[2026, 2027],
    )
    assert queries == ["devops conference amsterdam"]


def test_blank_keywords_are_skipped_not_turned_into_bare_queries():
    """An empty row in the settings list must not become a query for
    'conference 2026', which would return unrelated noise."""
    queries = build_queries(
        keywords=["AI", "", "   "],
        templates=["{keyword} conference {year}"],
        years=[2026],
    )
    assert queries == ["AI conference 2026"]


def test_no_keywords_yields_no_queries():
    assert build_queries(keywords=[], templates=["{keyword} conf"], years=[2026]) == []


# --- the sweep itself ------------------------------------------------------
@pytest.mark.asyncio
async def test_one_failing_query_does_not_cost_the_other_results(monkeypatch):
    """The whole point of catching per-query. DDG CAPTCHAs constantly; a
    sweep that dies on the first bad query is the old 20-result failure
    with extra steps."""
    calls: list[str] = []

    async def fake_search(*, prompt, provider, max_results, **kw):
        calls.append(prompt)
        if "boom" in prompt:
            raise RuntimeError("provider returned a CAPTCHA")
        return [SearchHit(url=f"https://example.com/{prompt}", title=prompt, snippet="")]

    monkeypatch.setattr(search_mod, "web_search", fake_search)

    hits = await web_search_many(
        queries=["good-one", "boom", "good-two"],
        provider="ddg",
        max_results_per_query=10,
    )

    assert len(calls) == 3, "every query should still be attempted"
    urls = {h.url for h in hits}
    assert urls == {"https://example.com/good-one", "https://example.com/good-two"}


@pytest.mark.asyncio
async def test_union_is_deduped_by_url_and_keeps_first_seen_order(monkeypatch):
    """Different phrasings surface overlapping pages. The union must keep
    each page once, and the earlier query should win it."""

    async def fake_search(*, prompt, provider, max_results, **kw):
        if prompt == "q1":
            return [
                SearchHit(url="https://a.example", title="from-q1", snippet=""),
                SearchHit(url="https://b.example", title="b", snippet=""),
            ]
        return [
            SearchHit(url="https://a.example", title="from-q2", snippet=""),
            SearchHit(url="https://c.example", title="c", snippet=""),
        ]

    monkeypatch.setattr(search_mod, "web_search", fake_search)

    hits = await web_search_many(
        queries=["q1", "q2"], provider="ddg", max_results_per_query=10
    )

    assert [h.url for h in hits] == [
        "https://a.example",
        "https://b.example",
        "https://c.example",
    ]
    assert hits[0].title == "from-q1", "first query to find a URL should win it"


@pytest.mark.asyncio
async def test_every_query_runs_even_when_all_of_them_fail(monkeypatch):
    """A total provider outage should return empty, not raise — the
    orchestrator still has seed URLs to fall back on."""

    async def fake_search(**kw):
        raise RuntimeError("down")

    monkeypatch.setattr(search_mod, "web_search", fake_search)
    assert await web_search_many(
        queries=["a", "b"], provider="ddg", max_results_per_query=5
    ) == []


@pytest.mark.asyncio
async def test_empty_query_list_makes_no_provider_calls(monkeypatch):
    called = False

    async def fake_search(**kw):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(search_mod, "web_search", fake_search)
    assert await web_search_many(queries=[], provider="ddg", max_results_per_query=5) == []
    assert called is False


# --- the operator can actually reach these ---------------------------------
def test_keyword_settings_are_editable_from_the_ui():
    """The keyword list is the biggest lever on recall. If it is not in
    SPECS it is not on the settings page, and the operator cannot change
    what Scout hunts for without a redeploy."""
    names = {s.name for s in SPECS}
    assert "discovery_keywords" in names
    assert "discovery_query_templates" in names
    assert "discovery_max_results_per_query" in names
    assert "discovery_max_urls_per_run" in names


# --- the feed filter -------------------------------------------------------
def test_feed_keyword_filter_is_off_by_default():
    """Measured against the live developers.events feed, this filter
    dropped 375 of 801 future events — including KeyCloakCon (our own
    project), ArgoCon, and Open Source Summit Korea.

    It existed to control volume, and there is no volume to control: 801
    future events is a trivial number of rows. Recall is the objective,
    so the default must stay off. If someone flips it back, this test
    should make them say why.
    """
    from app.services.discovery import FeedFilters

    assert FeedFilters().only_ai is False
    # Future-only stays ON: a conference that already happened cannot be
    # attended, so dropping it costs no recall.
    assert FeedFilters().future_only is True


def test_feed_result_reports_what_the_filter_dropped():
    """A filter whose losses nobody counts looks free. If filtering is
    switched on, the run result has to say what it cost."""
    from app.services.discovery import FeedIngestResult

    r = FeedIngestResult(
        source="x", total_in_feed=0, matched_filter=0, new_conferences=0,
        updated_conferences=0, skipped_duplicate=0, errors=0,
    )
    assert r.dropped_by_keyword_filter == 0
    assert "dropped_by_keyword_filter" in r.to_dict()


# --- aggregator link extraction --------------------------------------------
REAL_CONFERENCE_URLS = [
    "https://javazone.no/",
    "https://gophercon.com/",
    "https://devoxx.be/",
    "https://qconlondon.com/",
    "https://aiengineer.dev/",
    "https://kcdtexas.com/",
    "https://www.rustconf.com/",
    "https://fosdem.org/2026/",
]


def test_conferences_named_after_themselves_are_not_dropped():
    """The gate used to require a 'conference-like' token in the URL, and
    rejected 7 of 15 real conferences because an established event lives
    on a domain named after itself — gophercon.com has no such token and
    never will. No amount of extending the word list fixes that shape.
    """
    from app.services.discovery import extract_conference_links

    md = "\n".join(f"[{u}]({u})" for u in REAL_CONFERENCE_URLS)
    got = extract_conference_links(md, source_url="https://aggregator.example", max_links=50)

    missing = [u.rstrip("/") for u in REAL_CONFERENCE_URLS if u.rstrip("/") not in got]
    assert not missing, f"real conferences dropped by the link gate: {missing}"


def test_conference_looking_links_are_spent_first():
    """Prioritisation is what makes a permissive gate affordable: when the
    budget is small it should buy the likeliest candidates."""
    from app.services.discovery import extract_conference_links

    md = (
        "[plain](https://acme.example/team)\n"
        "[hinted](https://acme.example/call-for-papers)\n"
        "[plain2](https://beta.example/home)\n"
    )
    got = extract_conference_links(md, source_url="https://x.example", max_links=1)
    assert got == ["https://acme.example/call-for-papers"]


def test_site_furniture_is_still_refused():
    """A permissive gate is not an absent one. These are safe to drop as a
    hard filter because they describe what every website has, so a false
    positive costs a wasted fetch and never a missed conference."""
    from app.services.discovery import extract_conference_links

    md = "\n".join(
        f"[x]({u})"
        for u in [
            "https://acme.example/login",
            "https://acme.example/privacy",
            "https://acme.example/docs/getting-started",
            "https://acme.example/brochure.pdf",
            "https://acme.example/logo.png",
            "https://acme.example/kubecon-2026",
        ]
    )
    got = extract_conference_links(md, source_url="https://x.example", max_links=50)
    assert got == ["https://acme.example/kubecon-2026"]


def test_operator_blocklist_still_wins():
    from app.services.discovery import extract_conference_links

    md = "[a](https://wikipedia.org/wiki/Conference)\n[b](https://real.example/summit)"
    got = extract_conference_links(
        md,
        source_url="https://x.example",
        blocklist_substrings=["wikipedia.org"],
        max_links=50,
    )
    assert got == ["https://real.example/summit"]


# --- SSRF ------------------------------------------------------------------
NON_PUBLIC = [
    "http://127.0.0.1/admin",
    "http://localhost:8080/",
    "http://169.254.169.254/latest/meta-data/",   # cloud metadata
    "http://10.0.0.5/internal",
    "http://192.168.1.1/",
    "https://[::1]/x",
]


@pytest.mark.parametrize("url", NON_PUBLIC)
def test_discovery_refuses_non_public_urls(url):
    """Discovery hands URLs to Crawl4AI, which drives a headless browser
    with its own network stack — so the SSRF-guarded httpx transport in
    services/discovery.py never sees them.

    The URLs come from search-engine results and from links mined out of
    third-party aggregator pages. Both are influenceable by someone who is
    not us, which makes an unscreened discovery run a request-forgery
    primitive aimed wherever a page says.
    """
    from app.services.discovery import is_public_url

    assert is_public_url(url) is False, f"{url} should not be fetchable"


def test_ordinary_conference_urls_are_still_allowed():
    from app.services.discovery import is_public_url

    assert is_public_url("https://kubecon.io/") is True


def test_malformed_urls_are_refused_rather_than_crashing():
    from app.services.discovery import is_public_url

    for junk in ["", "not-a-url", "http://", "///"]:
        assert is_public_url(junk) is False


def test_both_crawl_paths_screen_their_urls():
    """Two lists reach crawl_many: search hits + seeds, and links mined
    from seed pages. The second is the riskier one — it never passes
    through the first list, so screening only the first would leave the
    wider hole open."""
    import ast
    import pathlib

    src = pathlib.Path("app/services/discovery.py").read_text()
    assert src.count("is_public_url(") >= 2, (
        "both the search-hit list and the mined-link list must be screened"
    )
    # crawl_many is the single fetch entry point; make sure it is still the
    # only one, or a third unscreened path could appear unnoticed.
    tree = ast.parse(src)
    calls = [
        n.func.id
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    ]
    assert calls.count("crawl_many") == 2, (
        "a new crawl path appeared — screen its URLs with is_public_url too"
    )


# --- robots.txt ------------------------------------------------------------
@pytest.mark.asyncio
async def test_a_robots_failure_does_not_silently_drop_a_conference():
    """The failure mode that matters here.

    If robots.txt cannot be fetched — host down, DNS broken, timeout —
    the URL must stay in. A crawl policy that drops candidates whenever a
    network call fails is a recall bug wearing a politeness costume, and
    it would be invisible: the run just returns fewer conferences.
    """
    from app.services.discovery import (
        DiscoveryResult,
        _drop_robots_disallowed,
    )

    result = DiscoveryResult(
        prompt="x", provider="ddg", requested=1, search_hits=0, crawled=0,
        new_conferences=0, updated_conferences=0, parse_failures=0,
    )
    # A host that cannot resolve: robots cannot be fetched, so the
    # candidate must survive.
    hits = [SearchHit(url="https://nx-does-not-resolve.invalid/cfp", title="t", snippet="")]
    kept = await _drop_robots_disallowed(hits, result)
    assert [h.url for h in kept] == [hits[0].url]
    assert result.dropped_robots == 0


@pytest.mark.asyncio
async def test_empty_hit_list_makes_no_network_calls():
    from app.services.discovery import (
        DiscoveryResult,
        _drop_robots_disallowed,
    )

    result = DiscoveryResult(
        prompt="x", provider="ddg", requested=1, search_hits=0, crawled=0,
        new_conferences=0, updated_conferences=0, parse_failures=0,
    )
    assert await _drop_robots_disallowed([], result) == []


def test_discovery_and_the_scraper_share_one_robots_policy():
    """A deployment should not be a good citizen on one fetch path and not
    the other. Discovery uses the same RobotsCache the curated scraper
    does, so a host is asked once a day and answered consistently."""
    import pathlib

    src = pathlib.Path("app/services/discovery.py").read_text()

    # Used to assert the orchestrator IMPORTED RobotsCache from the scraper
    # package. Both paths now live in this one module, so the import is
    # gone and the invariant has to be stated directly: one definition,
    # and both fetch paths reach for it.
    assert src.count("class RobotsCache") == 1, (
        "two robots caches means two policies, which is the bug this guards"
    )
    assert src.count("RobotsCache(") >= 1
    assert "scraper_user_agent" in src, (
        "robots must be evaluated against the UA we actually send"
    )
