/**
 * /agent — chat panel (plan 22).
 *
 * Sessions sidebar + message stream + composer. Read-only RAG; every
 * concrete claim from the assistant carries a numbered citation chip.
 *
 * Pass-1 scope: non-streaming ask/reply, session create/list/archive,
 * citation chips with click-to-source for conferences.
 * Deferred: SSE streaming, /slash commands, cost meter widget, rename
 *           sessions UI, cancel button.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { Link, createFileRoute } from "@tanstack/react-router";
import { useEffect, useMemo, useRef, useState } from "react";

import { MarkdownText } from "@/components/agent/MarkdownText";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, agentApi } from "@/lib/api";
import type { AgentCitation, AgentMessage } from "@/lib/api-types";
import { PageBanner, PageHeader } from "@/routes/dashboard";

export const Route = createFileRoute("/agent")({
  component: AgentPage,
});

function AgentPage() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const sessionsQ = useQuery({
    queryKey: ["agent", "sessions"],
    queryFn: () => agentApi.listSessions({ include_archived: false, limit: 30 }),
  });

  // Bootstrap: if no session selected, pick the most recent.
  useEffect(() => {
    if (sessionId || sessionsQ.isLoading) return;
    const first = sessionsQ.data?.sessions?.[0];
    if (first) {
      setSessionId(first.id);
    }
  }, [sessionId, sessionsQ.data, sessionsQ.isLoading]);

  const newSessionMut = useMutation({
    mutationFn: () => agentApi.createSession(),
    onSuccess: (s) => {
      void queryClient.invalidateQueries({ queryKey: ["agent", "sessions"] });
      setSessionId(s.id);
    },
  });

  const archiveMut = useMutation({
    mutationFn: (id: string) => agentApi.archiveSession(id),
    onSuccess: (_, id) => {
      void queryClient.invalidateQueries({ queryKey: ["agent", "sessions"] });
      if (id === sessionId) {
        setSessionId(null);
      }
    },
  });

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Agent chat"
        description="Ask questions about SCOUT's data in plain English."
      />

      <PageBanner>
        The agent searches across conferences, SMEs, matches, and past events to answer your
        question — and cites exactly where each fact came from. Use it for one-off lookups like
        "which conferences in Europe match our AI pillar?" or "which SMEs have spoken at KubeCon?"
        Everything here is <strong>read-only</strong>; no changes are made to the database.
        For bulk changes, use the Workbook import in Settings.
      </PageBanner>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[260px_1fr]">
        <SessionSidebar
          sessions={sessionsQ.data?.sessions ?? []}
          loading={sessionsQ.isLoading}
          activeId={sessionId}
          onSelect={setSessionId}
          onNew={() => newSessionMut.mutate()}
          onArchive={(id) => archiveMut.mutate(id)}
          newPending={newSessionMut.isPending}
        />

        {sessionId ? (
          <ChatPanel sessionId={sessionId} />
        ) : (
          <Card>
            <CardContent className="flex h-[640px] flex-col items-center justify-center gap-3 text-center">
              <p className="text-sm text-fg-muted">
                No session selected. Start a new conversation to ask Scout
                questions about its conference data.
              </p>
              <Button
                onClick={() => newSessionMut.mutate()}
                disabled={newSessionMut.isPending}
              >
                {newSessionMut.isPending ? "Creating…" : "New chat"}
              </Button>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sidebar
// ---------------------------------------------------------------------------
function SessionSidebar({
  sessions,
  loading,
  activeId,
  onSelect,
  onNew,
  onArchive,
  newPending,
}: {
  sessions: import("@/lib/api-types").AgentSession[];
  loading: boolean;
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onArchive: (id: string) => void;
  newPending: boolean;
}) {
  return (
    <Card className="h-[640px] overflow-hidden">
      <CardContent className="flex h-full flex-col gap-2 p-3">
        <Button
          onClick={onNew}
          disabled={newPending}
          className="w-full"
          size="sm"
        >
          {newPending ? "Creating…" : "+ New chat"}
        </Button>
        <div className="-mr-1 mt-2 flex-1 overflow-y-auto pr-1">
          {loading ? (
            <div className="flex flex-col gap-2">
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
            </div>
          ) : sessions.length === 0 ? (
            <p className="px-2 py-4 text-xs text-fg-muted">No conversations yet.</p>
          ) : (
            <ul className="flex flex-col gap-1">
              {sessions.map((s) => (
                <li key={s.id} className="group flex items-center gap-1">
                  <button
                    type="button"
                    onClick={() => onSelect(s.id)}
                    className={[
                      "min-w-0 flex-1 truncate rounded-md px-2 py-2 text-left text-xs",
                      activeId === s.id
                        ? "bg-surface-2 text-fg"
                        : "text-fg-muted hover:bg-surface-2 hover:text-fg",
                    ].join(" ")}
                    title={s.title ?? "Untitled"}
                  >
                    {s.title ?? "Untitled chat"}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      if (confirm("Archive this conversation?")) onArchive(s.id);
                    }}
                    className="hidden rounded-md p-1 text-fg-subtle hover:bg-surface-3 hover:text-fg group-hover:block"
                    aria-label="Archive"
                  >
                    ×
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Main chat panel
// ---------------------------------------------------------------------------
function ChatPanel({ sessionId }: { sessionId: string }) {
  const queryClient = useQueryClient();
  const messagesQ = useQuery({
    queryKey: ["agent", "messages", sessionId],
    queryFn: () => agentApi.listMessages(sessionId),
  });

  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const scrollerRef = useRef<HTMLDivElement | null>(null);

  const ask = useMutation({
    mutationFn: (content: string) => agentApi.ask(sessionId, content),
    onSuccess: () => {
      setDraft("");
      setError(null);
      void queryClient.invalidateQueries({
        queryKey: ["agent", "messages", sessionId],
      });
      // The first user message may have populated the session title.
      void queryClient.invalidateQueries({ queryKey: ["agent", "sessions"] });
    },
    onError: (err) => {
      setError(
        err instanceof ApiError ? err.problem.detail ?? err.problem.title : String(err),
      );
    },
  });

  const messages = messagesQ.data?.messages ?? [];
  const lastMessageCount = useRef(messages.length);

  // Auto-scroll to bottom when a new message arrives.
  useEffect(() => {
    if (messages.length !== lastMessageCount.current) {
      const el = scrollerRef.current;
      if (el) el.scrollTop = el.scrollHeight;
      lastMessageCount.current = messages.length;
    }
  }, [messages.length]);

  const totalCost = useMemo(() => {
    return messages.reduce((acc, m) => acc + (m.metadata_json?.cost_usd ?? 0), 0);
  }, [messages]);

  return (
    <Card className="flex h-[640px] flex-col overflow-hidden">
      <CardContent className="flex h-full flex-col gap-3 p-0">
        <div
          ref={scrollerRef}
          className="flex-1 space-y-4 overflow-y-auto px-4 py-4"
        >
          {messagesQ.isLoading ? (
            <Skeleton className="h-20 w-full" />
          ) : messages.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center gap-2 text-center text-sm text-fg-muted">
              <p>Ask Scout anything about its conference data.</p>
              <p className="text-xs text-fg-subtle">
                e.g. "Which conferences should I prioritize this quarter?"
              </p>
            </div>
          ) : (
            messages.map((m) => <MessageBubble key={m.id} m={m} />)
          )}
          {ask.isPending ? (
            <div className="flex gap-3">
              <div className="flex-1 rounded-lg bg-surface-2 p-3 text-sm text-fg-muted">
                <Skeleton className="mb-2 h-3 w-1/3" />
                <Skeleton className="mb-2 h-3 w-2/3" />
                <Skeleton className="h-3 w-1/2" />
              </div>
            </div>
          ) : null}
        </div>

        <div className="border-t border-border bg-surface-1 px-4 py-3">
          {error ? (
            <p className="mb-2 rounded-md border border-danger/30 bg-danger/10 p-2 text-xs text-danger">
              {error}
            </p>
          ) : null}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const value = draft.trim();
              if (!value || ask.isPending) return;
              ask.mutate(value);
            }}
            className="flex items-end gap-2"
          >
            <Textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  const value = draft.trim();
                  if (!value || ask.isPending) return;
                  ask.mutate(value);
                }
              }}
              placeholder="Ask about a conference, an SME, why a score is what it is…"
              className="min-h-[60px] flex-1 resize-y"
              disabled={ask.isPending}
            />
            <Button type="submit" disabled={!draft.trim() || ask.isPending}>
              {ask.isPending ? "Asking…" : "Send"}
            </Button>
          </form>
          <p className="mt-2 flex items-center justify-between text-xs text-fg-muted">
            <span>
              Enter to send · Shift+Enter for newline · Cited claims open the
              source.
            </span>
            <span className="font-medium text-fg tabular-nums">
              Session cost: ${totalCost.toFixed(4)}
            </span>
          </p>
        </div>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Single message
// ---------------------------------------------------------------------------
function MessageBubble({ m }: { m: AgentMessage }) {
  const isUser = m.role === "user";
  const citations = m.metadata_json?.citations ?? [];
  return (
    <div className={isUser ? "flex justify-end" : "flex justify-start"}>
      <div
        className={[
          "max-w-[80%] rounded-lg px-3 py-2 text-sm",
          isUser
            ? "bg-accent text-accent-fg"
            : "bg-surface-2 text-fg",
        ].join(" ")}
      >
        {isUser ? (
          <p className="whitespace-pre-wrap">{m.content}</p>
        ) : (
          <MarkdownText>{m.content}</MarkdownText>
        )}
        {!isUser && citations.length > 0 ? (
          <div className="mt-2 flex flex-wrap gap-1">
            {citations.map((c) => (
              <CitationChip key={`${c.index}-${c.chunk_id}`} c={c} />
            ))}
          </div>
        ) : null}
        {!isUser && m.metadata_json?.cost_usd !== undefined ? (
          <p className="mt-1 text-xs text-fg-muted">
            {m.metadata_json.completion_tokens ?? 0} tokens · $
            {(m.metadata_json.cost_usd ?? 0).toFixed(4)}
          </p>
        ) : null}
      </div>
    </div>
  );
}

function CitationChip({ c }: { c: AgentCitation }) {
  // Conferences are the only owner type with a built-in detail route in pass 1.
  if (c.owner_type === "conference") {
    return (
      <Link
        to="/conferences/$id"
        params={{ id: c.owner_id }}
        className="rounded-full border border-border bg-surface-3 px-2 py-0.5 text-[11px] text-fg hover:border-accent hover:text-accent"
        title={c.label}
      >
        [{c.index}] {c.label}
      </Link>
    );
  }
  return (
    <Badge variant="muted" className="text-[11px]" title={c.label}>
      [{c.index}] {c.label}
    </Badge>
  );
}
