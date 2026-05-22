"""Per-model price table and cost calculation.

Prices below match the Red Hat MaaS catalog as of 2026-05 (the screenshot
the user provided when locking in the chat + embedding models). Overridable
via the ``LLM_PRICES_JSON`` env var if MaaS adjusts pricing.

Cost is always USD per *million* tokens; computed cost is in USD.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

import structlog

log = structlog.get_logger("scout.llm.costs")


@dataclass(frozen=True)
class Price:
    """USD per million tokens, input + output."""

    input_per_million: float
    output_per_million: float


# Hard-coded defaults from the MaaS catalog. Keep this list narrow — only
# models we actually configure via env.
_DEFAULT_PRICES: dict[str, Price] = {
    # Chat
    "granite-3-2-8b-instruct": Price(0.50, 0.50),
    "granite-4-0-h-tiny": Price(0.05, 0.05),
    "deepseek-r1-distill-qwen-14b": Price(0.80, 0.80),
    "openai/deepseek-r1-distill-qwen-14b": Price(0.80, 0.80),
    "qwen3-14b": Price(0.80, 0.80),
    "llama-scout-17b": Price(1.07, 1.07),
    "codellama-7b-instruct": Price(0.40, 0.40),
    "microsoft-phi-4": Price(0.00, 0.00),
    "Llama-Guard-3-1B": Price(0.10, 0.10),
    # Embeddings
    "nomic-embed-text-v1-5": Price(0.02, 0.00),  # embeddings are input-only
}


def _load_overrides() -> dict[str, Price]:
    """Parse LLM_PRICES_JSON if set. Format: ``{"model-name": {"input": 0.5, "output": 0.5}}``."""
    raw = os.environ.get("LLM_PRICES_JSON")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return {
            name: Price(float(p["input"]), float(p["output"]))
            for name, p in data.items()
        }
    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
        log.warning("llm_prices_json.invalid", error=str(exc))
        return {}


_PRICES: dict[str, Price] = {**_DEFAULT_PRICES, **_load_overrides()}


def get_price(model: str) -> Price | None:
    """Return the price for a model, or None if we don't have one (so the
    caller can log + zero-cost the record rather than crash)."""
    return _PRICES.get(model)


def compute_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Return cost in USD for a single call. Unknown model → 0.0 with a warn log."""
    price = _PRICES.get(model)
    if price is None:
        log.warning("llm.cost.unknown_model", model=model)
        return 0.0
    return (
        prompt_tokens * price.input_per_million / 1_000_000
        + completion_tokens * price.output_per_million / 1_000_000
    )
