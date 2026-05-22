"""LLM service layer.

A provider-agnostic abstraction over LLM API via the OpenAI-compatible API.
Same client for chat and embeddings. Retries, cost accounting, dry-run mode,
budget guardrail.

Public surface:
    from app.services.llm import LLMClient, BudgetExceeded, get_llm_client

See ``PLANS/phase-1/10-llm-service-layer.md`` for the design + open questions
and ``PLANS/phase-1/09-llm-service-layer.md`` for related details.
"""

from app.services.llm.client import LLMClient, get_llm_client
from app.services.llm.models import (
    BudgetExceeded,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    EmbeddingRequest,
    EmbeddingResponse,
)

__all__ = [
    "BudgetExceeded",
    "ChatMessage",
    "ChatRequest",
    "ChatResponse",
    "EmbeddingRequest",
    "EmbeddingResponse",
    "LLMClient",
    "get_llm_client",
]
