"""Type definitions for the LLM client.

These are internal to the LLM layer — callers downstream (matcher, agent
chat, etc.) talk to the LLMClient with these shapes, never raw OpenAI SDK
types. That isolates us from upstream SDK churn.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------
class ChatMessage(BaseModel):
    """One turn in a chat completion call."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str


class ChatRequest(BaseModel):
    """Inputs to LLMClient.chat. Provider-agnostic on purpose; the client
    translates this to the OpenAI-compatible wire format."""

    model_config = ConfigDict(extra="forbid")

    messages: list[ChatMessage]
    purpose: str = Field(
        ...,
        description="Tag for cost-tracking (e.g. 'extract_conference', 'rationale').",
    )
    model: str | None = None
    temperature: float = 0.2
    max_tokens: int | None = None
    response_format: dict[str, Any] | None = None  # e.g. {"type": "json_object"}
    stream: bool = False


class ChatResponse(BaseModel):
    """What LLMClient.chat returns. Streaming responses produce a
    different shape (an async iterator) and are not represented here."""

    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    latency_ms: int
    request_id: str
    raw: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------
class EmbeddingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    texts: list[str]
    purpose: str
    model: str | None = None


class EmbeddingResponse(BaseModel):
    """A flat aligned list of vectors (same order as inputs)."""

    vectors: list[list[float]]
    model: str
    prompt_tokens: int
    cost_usd: float
    latency_ms: int


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class BudgetExceeded(Exception):
    """Raised when a non-forced call would push monthly spend past the cap.

    The api route layer maps this to HTTP 503 with a problem+json body that
    tells the user to bump LLM_MONTHLY_BUDGET_USD or wait until next month.
    """

    def __init__(self, *, month_spend: float, budget: float):
        super().__init__(
            f"Month-to-date LLM spend ${month_spend:.2f} would exceed "
            f"the configured budget ${budget:.2f}."
        )
        self.month_spend = month_spend
        self.budget = budget
