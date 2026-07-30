"""The maintenance CLI must stay wired and importable.

``python -m app.maintenance`` is the operator's recovery path — re-embedding
after a model rollover, re-enriching pillars, refreshing conference status.
It reaches into a few private service helpers so the text it embeds is
byte-identical to what a normal save produces, which makes it sensitive to
renames elsewhere.

These tests do not execute the commands (they need a database and an LLM
endpoint). They prove the module imports, every subcommand is registered,
the flags parse, and the helpers it depends on still exist.
"""

from __future__ import annotations

import pytest
from app import maintenance

EXPECTED_COMMANDS = {
    "enrich-conferences",
    "enrich-pillars",
    "reembed-owners",
    "backfill-conference-embeddings",
    "refresh-statuses",
    "reparse-pages",
}


def _subcommands() -> set[str]:
    parser = maintenance.build_parser()
    for action in parser._actions:
        if action.dest == "command" and action.choices:
            return set(action.choices)
    raise AssertionError("no subparser registered on the maintenance parser")


def test_every_command_is_registered() -> None:
    assert _subcommands() == EXPECTED_COMMANDS


@pytest.mark.parametrize("command", sorted(EXPECTED_COMMANDS))
def test_command_parses_with_defaults(command: str) -> None:
    args = maintenance.build_parser().parse_args([command])
    assert args.command == command


def test_missing_command_exits_nonzero() -> None:
    with pytest.raises(SystemExit) as exc:
        maintenance.build_parser().parse_args([])
    assert exc.value.code != 0


def test_unknown_command_exits_nonzero() -> None:
    with pytest.raises(SystemExit) as exc:
        maintenance.build_parser().parse_args(["not-a-command"])
    assert exc.value.code != 0


def test_flags_are_wired() -> None:
    parser = maintenance.build_parser()
    assert parser.parse_args(["enrich-conferences", "--force"]).force is True
    assert parser.parse_args(["enrich-conferences"]).force is False
    assert (
        parser.parse_args(["enrich-conferences", "--concurrency", "3"]).concurrency == 3
    )
    assert parser.parse_args(["enrich-pillars", "--force"]).force is True
    assert parser.parse_args(["refresh-statuses", "--dry-run"]).dry_run is True
    # The default must be WRITE, matching the old script's behaviour — the
    # dry-run is an opt-in review step, not a safety net that silently
    # turns the command into a no-op.
    assert parser.parse_args(["refresh-statuses"]).dry_run is False
    assert (
        parser.parse_args(
            ["backfill-conference-embeddings", "--batch-size", "5"]
        ).batch_size
        == 5
    )


def test_the_embed_text_builders_the_commands_depend_on_still_exist() -> None:
    """The re-embed commands must produce the SAME text a normal save does.

    That is the real contract: if `maintenance reembed-owners` built its
    text differently from the service that writes on every edit, a re-embed
    would silently change what is stored and every affected score would
    drift with no visible cause.

    This used to pin five UNDERSCORE-prefixed helpers imported from outside
    their own modules — a guard written around a boundary problem instead of
    a fix for it. All five are public now: a leading underscore is a claim
    about who may call something, and when callers in other packages
    disagree with the claim, the name is what is wrong.
    """
    from app.services.conferences import conference_embed_text
    from app.services.matcher import choose_status
    from app.services.positioning import load_messaging_corpus, messaging_embed_text
    from app.services.taxonomy import audience_embed_text

    for fn in (
        audience_embed_text,
        conference_embed_text,
        choose_status,
        messaging_embed_text,
        load_messaging_corpus,
    ):
        assert callable(fn)


def test_enrich_conferences_does_not_delete_across_embedding_models() -> None:
    """The command must not delete chunks itself.

    ``embed_owner`` already replaces an owner's chunks, scoped to the ACTIVE
    embedding model. A broader delete here would wipe vectors stored under a
    deprecated model, which is what makes an embedding-model rollover
    reversible.
    """
    import inspect

    src = inspect.getsource(maintenance.enrich_conferences)
    assert "delete(DocumentChunk)" not in src, (
        "enrich-conferences must not delete chunks itself — embed_owner "
        "already replaces them, scoped to the active embedding model"
    )


def test_reparse_pages_is_reachable_from_the_cli() -> None:
    """The command that fills real descriptions into conferences created
    before the column existed.

    Those rows fall back to enriched_description — text an LLM invented
    from the conference's name — which the matcher scores and the judge
    reasons about. The real page was never discarded; services/scraper
    stores every fetch. This re-runs extraction over what is already on
    disk: no re-crawl, no politeness cost, no risk the site has changed.

    It matters more now that discovery ingests broadly. Judging hundreds
    of conferences on invented descriptions is vetoing at scale on
    guesses.
    """
    from app.maintenance import build_parser

    args = build_parser().parse_args(["reparse-pages"])
    assert args.command == "reparse-pages"
    # Default is the set that actually needs it, not every page ever
    # fetched — one LLM call each adds up.
    assert args.only_missing_description is True
    assert args.limit is None


def test_reparse_pages_can_be_widened_and_bounded() -> None:
    from app.maintenance import build_parser

    args = build_parser().parse_args(["reparse-pages", "--all", "--limit", "50"])
    assert args.only_missing_description is False
    assert args.limit == 50
