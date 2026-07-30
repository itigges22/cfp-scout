"""Every model we actually run must have a price.

An unpriced model records $0.00 per call. That is not a cosmetic gap: the
monthly budget guardrail sums recorded cost, so an unpriced model makes the
cap unreachable and spending invisible. The lookup is an exact dict match on
the model string, so a rename or a case change is enough to break it.
"""

from __future__ import annotations

import pytest
from app.services.llm import _DEFAULT_PRICES, compute_cost
from app.settings import Settings


def _default(field: str) -> str:
    return Settings.model_fields[field].default


@pytest.mark.parametrize("field", ["llm_chat_model", "llm_embedding_model"])
def test_the_configured_default_model_has_a_price(field: str) -> None:
    model = _default(field)
    assert model in _DEFAULT_PRICES, (
        f"{field} defaults to {model!r}, which has no entry in _DEFAULT_PRICES. "
        f"Every call with it records $0.00 and the monthly budget cap can "
        f"never trigger."
    )


def test_a_priced_chat_model_produces_non_zero_cost() -> None:
    model = _default("llm_chat_model")
    assert compute_cost(model, prompt_tokens=1_000_000, completion_tokens=0) > 0


def test_embeddings_are_input_only() -> None:
    """Embedding models bill on input; output tokens must not add cost."""
    model = _default("llm_embedding_model")
    only_input = compute_cost(model, prompt_tokens=1_000_000, completion_tokens=0)
    with_output = compute_cost(model, prompt_tokens=1_000_000, completion_tokens=500_000)
    assert only_input > 0
    assert only_input == with_output


def test_unknown_model_is_free_and_does_not_raise() -> None:
    """Unknown models must degrade to 0.0 rather than break the call path —
    but the test above is what stops the models we run landing here."""
    assert compute_cost("not-a-real-model", 1000, 1000) == 0.0


def test_lookup_is_exact_so_case_matters() -> None:
    model = _default("llm_embedding_model")
    assert compute_cost(model.lower(), 1_000_000, 0) == 0.0 or model.islower(), (
        "model lookup is an exact dict match; a case-mismatched name silently "
        "prices at zero"
    )
