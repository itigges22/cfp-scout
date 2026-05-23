/**
 * Reusable multi-turn agent chat panel.
 *
 * Owns the conversation: lazily creates a session on first send, persists
 * it via the `storageKey` so navigating away and coming back keeps the
 * thread, and renders the message stream with markdown.
 *
 * Used by:
 *   - the dashboard (compact mode, sits beside the world map)
 *   - the full /agent page (eventually — pass 2)
 *
 * Composer convention is the same as /agent: Enter to send,
 * Shift+Enter for newline.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Send, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { MarkdownText } from "@/components/agent/MarkdownText";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { agentApi } from "@/lib/api";
import type { AgentCitation, AgentMessage } from "@/lib/api-types";

interface Props {
  /** Title shown in the header. */
  title?: string;
  /** localStorage key used to remember which session this panel uses. */
  storageKey: string;
  /** Default session title when one is lazily created. */
  defaultSessionTitle?: string;
  /** Placeholder copy in the composer. */
  placeholder?: string;
  /** Show the session-cost meter in the footer? */
  showCost?: boolean;
}

export function AgentChatPanel({
  title = "Ask Scout",
  storageKey,
  defaultSessionTitle = "Dashboard chat",
  placeholder = "Ask about a conference, SME, or anything in Scout's data…",
  showCost = true,
}: Props) {
  const qc = useQueryClient();
  const [sessionId, setSessionId] = useState<string | null>(() => {
    if (typeof window === "undefined") return null;
    return window.localStorage.getItem(storageKey);
  });
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const scrollerRef = useRef<HTMLDivElement | null>(null);

  // Pull the message history for the active session (if any).
  const messagesQ = useQuery({
    queryKey: ["agent-panel", "messages", sessionId],
    queryFn: () => agentApi.listMessages(sessionId!),
    enabled: !!sessionId,
  });

  const sendMut = useMutation({
    mutationFn: async (content: string) => {
      let sid = sessionId;
      if (!sid) {
        const created = await agentApi.createSession(defaultSessionTitle);
        sid = created.id;
        setSessionId(sid);
        if (typeof window !== "undefined") {
          window.localStorage.setItem(storageKey, sid);
        }
      }
      const reply = await agentApi.ask(sid, content);
      return { sid, reply };
    },
    onSuccess: ({ sid }) => {
      setDraft("");
      void qc.invalidateQueries({ queryKey: ["agent-panel", "messages", sid] });
    },
    onError: (err) => setError(String((err as Error)?.message ?? err)),
  });

  // Auto-scroll to bottom when new messages land or while the reply is
  // streaming in (non-streaming mode, but the pending spinner needs to be
  // visible too).
  useEffect(() => {
    const el = scrollerRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [messagesQ.data?.messages?.length, sendMut.isPending]);

  const messages = messagesQ.data?.messages ?? [];
  const totalCost = messages.reduce(
    (acc, m) => acc + (m.metadata_json?.cost_usd ?? 0),
    0,
  );

  const handleSend = () => {
    const value = draft.trim();
    if (!value || sendMut.isPending) return;
    setError(null);
    sendMut.mutate(value);
  };

  const handleClear = async () => {
    if (!sessionId) return;
    if (!window.confirm("Start a fresh chat? The current thread will be archived.")) return;
    try {
      await agentApi.archiveSession(sessionId);
    } catch {
      /* archive failure isn't fatal — still cut the local link */
    }
    setSessionId(null);
    if (typeof window !== "undefined") {
      window.localStorage.removeItem(storageKey);
    }
  };

  return (
    <div className="flex h-full flex-col rounded-lg border border-border bg-surface-1">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border-subtle px-3 py-2">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold">{title}</h3>
          <Badge variant="muted" className="text-[10px]">
            grounded in your data
          </Badge>
        </div>
        {sessionId ? (
          <button
            type="button"
            onClick={handleClear}
            className="rounded p-1 text-fg-subtle hover:bg-surface-2 hover:text-fg"
            aria-label="Clear chat"
            title="Archive this thread and start fresh"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        ) : null}
      </div>

      {/* Message stream */}
      <div
        ref={scrollerRef}
        className="flex-1 space-y-3 overflow-y-auto px-3 py-3"
      >
        {!sessionId ? (
          <EmptyChat />
        ) : messagesQ.isLoading ? (
          <Skeleton className="h-24 w-full" />
        ) : messages.length === 0 && !sendMut.isPending ? (
          <EmptyChat />
        ) : (
          messages.map((m) => <Bubble key={m.id} m={m} />)
        )}
        {sendMut.isPending ? <PendingBubble /> : null}
      </div>

      {/* Composer */}
      <div className="border-t border-border-subtle bg-surface px-3 py-2">
        {error ? (
          <p className="mb-2 rounded border border-danger/30 bg-danger/10 px-2 py-1 text-xs text-danger">
            {error}
          </p>
        ) : null}
        <div className="flex items-end gap-2">
          <Textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            placeholder={placeholder}
            disabled={sendMut.isPending}
            className="min-h-[44px] flex-1 resize-none text-sm"
            rows={2}
          />
          <Button
            type="button"
            onClick={handleSend}
            disabled={!draft.trim() || sendMut.isPending}
            size="sm"
            className="self-stretch"
            aria-label="Send"
          >
            {sendMut.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Send className="h-4 w-4" />
            )}
          </Button>
        </div>
        <p className="mt-1 flex items-center justify-between text-[10px] text-fg-subtle">
          <span>Enter to send · Shift+Enter for newline</span>
          {showCost && totalCost > 0 ? (
            <span className="font-medium text-fg-muted tabular-nums">
              ${totalCost.toFixed(4)} this chat
            </span>
          ) : null}
        </p>
      </div>
    </div>
  );
}

function EmptyChat() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 px-4 py-8 text-center text-xs text-fg-subtle">
      <p className="text-sm font-medium text-fg-muted">No messages yet.</p>
      <p>
        Ask things like "<em>which AI conferences in Europe close their CFP
        this month?</em>" or "<em>who should we send to ICML 2027?</em>"
      </p>
    </div>
  );
}

function PendingBubble() {
  return (
    <div className="flex justify-start">
      <div className="max-w-[85%] rounded-lg bg-surface-2 px-3 py-2 text-sm text-fg-muted">
        <div className="flex items-center gap-2">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          <span className="text-xs">Thinking…</span>
        </div>
      </div>
    </div>
  );
}

function Bubble({ m }: { m: AgentMessage }) {
  const isUser = m.role === "user";
  const citations = m.metadata_json?.citations ?? [];
  return (
    <div className={isUser ? "flex justify-end" : "flex justify-start"}>
      <div
        className={[
          "max-w-[85%] rounded-lg px-3 py-2 text-sm",
          isUser ? "bg-accent text-accent-fg" : "bg-surface-2 text-fg",
        ].join(" ")}
      >
        {isUser ? (
          <p className="whitespace-pre-wrap leading-relaxed">{m.content}</p>
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
      </div>
    </div>
  );
}

function CitationChip({ c }: { c: AgentCitation }) {
  return (
    <Badge
      variant="muted"
      className="text-[10px]"
      title={`${c.label} (similarity ${(c.similarity ?? 0).toFixed(2)})`}
    >
      [{c.index}] {c.label}
    </Badge>
  );
}
