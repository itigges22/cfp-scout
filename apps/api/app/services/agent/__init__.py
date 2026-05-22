"""Agent chat service (plan 22).

Read-only RAG. No tool calls, no autonomous mutations — the agent can
SUGGEST actions but the user clicks the button. Every claim carries a
numbered citation pointing back to the source it came from.

Public surface:
  * :func:`ask`              — single-turn ask: persists user message,
                                retrieves context, calls LLM, persists
                                assistant message with citations, returns
                                the assistant turn.
  * :class:`AgentReply`      — typed return.
  * :class:`Citation`        — one source citation row.
"""

from app.services.agent.service import AgentReply, Citation, ask

__all__ = ["AgentReply", "Citation", "ask"]
