"""Prompts must not seed both sides of the similarity comparison.

WHY THIS EXISTS
    enrichment.py generated a conference description and told the model
    which words to use: a fixed list — LLMs, inference, fine-tuning, RAG,
    embeddings, vector databases, MLOps, agentic AI, MCP, Kubernetes,
    hybrid cloud, open source AI — plus six worked examples naming vLLM,
    Kubeflow, PyTorch, llm-d.

    pillar_enrichment steered the OTHER side of the same cosine
    comparison toward the same words.

    So both vectors were being pushed toward one list we wrote, and the
    score partly measured agreement between two prompts rather than
    between a conference and the messaging.

    It was also the operator's technology domain hardcoded into a prompt.
    A team working on something else would need different words and could
    not change them. settings.operator_profile is where facts about the
    operator's world belong — it is already a setting, already injected
    into the judge, and already editable.

WHAT THIS DOES NOT CLAIM
    Removing the list has NOT been measured against the corpus, because
    no corpus conference exercises enrichment — they all carry real
    descriptions. See D2. The argument here is structural, not empirical,
    and the file says so rather than implying a measurement happened.
"""

from __future__ import annotations

import pytest

#: Terms specific to THIS operator's technology domain. A prompt that
#: injects these is deciding the vocabulary on the operator's behalf.
_OPERATOR_DOMAIN_TERMS = (
    "vLLM",
    "llm-d",
    "Kubeflow",
    "PyTorch",
    "InstructLab",
    "MCP",
    "RAG",
    "MLOps",
    "hybrid cloud",
    "agentic AI",
    "vector database",
)


def _prompt_body(text: str) -> str:
    """The prompt itself, excluding Python comments.

    Changelog comments legitimately NAME the terms they removed —
    "removed the list naming vLLM, Kubeflow…" is exactly the kind of
    note that should survive. Only what reaches the model counts.
    """
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )


def _domain_terms_in(text: str) -> list[str]:
    """Operator-domain terms appearing as WORDS, not as substrings.

    A plain ``in`` check reports "RAG" for the word "paragraphs" — which is
    how the pillar prompt looked like it named a product when it only said
    "write 4-7 paragraphs". Substring matching on short acronyms is all
    false positives.
    """
    import re as _re

    return [
        t
        for t in _OPERATOR_DOMAIN_TERMS
        if _re.search(rf"\b{_re.escape(t)}\b", text, _re.IGNORECASE)
    ]


def test_enrichment_does_not_dictate_vocabulary() -> None:
    from app.settings import get_settings

    _SYSTEM_PROMPT = get_settings().prompt_conference_enrichment

    found = [t for t in _OPERATOR_DOMAIN_TERMS if t.lower() in _SYSTEM_PROMPT.lower()]
    assert not found, (
        f"the enrichment prompt names operator-domain terms {found}. It "
        f"generates text that gets embedded and compared against the "
        f"messaging documents — naming the words to use seeds both sides "
        f"of that comparison. Put operator facts in "
        f"settings.operator_profile instead."
    )


def test_the_guards_that_matter_survived() -> None:
    """Shrinking the prompt must not lose the anti-fabrication rules.
    Those are machine contract, not operator vocabulary."""
    from app.settings import get_settings

    _SYSTEM_PROMPT = get_settings().prompt_conference_enrichment

    lowered = _SYSTEM_PROMPT.lower()
    assert "never invent" in lowered, "lost the no-fabrication rule"
    assert "marketing language" in lowered, "lost the no-marketing rule"
    assert "likely covers" in lowered, "lost the hedging instruction"


def test_the_prompt_version_moved_with_the_wording() -> None:
    """A stored extraction can be traced to the wording that produced it.
    Changing the prompt without bumping this makes that untrue."""
    from app.services.conferences import PROMPT_VERSION

    assert PROMPT_VERSION == "conference.enrichment.v2"


@pytest.mark.parametrize(
    "module,attr",
    [
        ("app.settings", "prompt_messaging_extraction"),
        ("app.settings", "prompt_pillar_enrichment"),
        ("app.settings", "prompt_talk_extraction"),
    ],
)
def test_extraction_prompts_stay_domain_neutral(module: str, attr: str) -> None:
    """These read a document the operator supplied and pull structure out
    of it. They have no reason to name a technology, and if one appears it
    is the same mistake in a new place."""
    import importlib

    if module == "app.settings":
        # Prompts are operator SETTINGS now, so the thing to check is the
        # live resolved value — a domain-neutral default that an override
        # replaces is still neutral where it ships.
        from app.settings import get_settings

        text = getattr(get_settings(), attr)
    else:
        text = getattr(importlib.import_module(module), attr)
    found = _domain_terms_in(text)
    assert not found, f"{module}.{attr} names operator-domain terms {found}"
