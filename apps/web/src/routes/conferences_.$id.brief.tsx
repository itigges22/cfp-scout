/**
 * /conferences/{id}/brief — print-optimized one-pager (plan 33).
 *
 * Single-column, no nav, no rail. Tailwind print styles below force a
 * clean Cmd-P → PDF. The on-screen view adds an export toolbar (Print /
 * Copy Markdown / Copy HTML / team-size switcher) — hidden in print.
 *
 * The logistics block is a `<div contenteditable>` persisted per-conf
 * to localStorage; never posted to the server.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, createFileRoute } from "@tanstack/react-router";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { conferencesApi } from "@/lib/api";
import type { ConferenceBrief } from "@/lib/api-types";


export const Route = createFileRoute("/conferences_/$id/brief")({
  validateSearch: () => ({}),
  component: ConferenceBriefPage,
});

function ConferenceBriefPage() {
  const { id } = Route.useParams();
  const briefQ = useQuery({
    queryKey: ["conferences", id, "brief"],
    queryFn: () => conferencesApi.brief(id),
    // The brief endpoint auto-runs the matcher when one is missing — that
    // can take 20+ seconds on first open. Keep the query patient.
    staleTime: 60_000,
    gcTime: 5 * 60_000,
  });

  if (briefQ.isLoading) {
    return <BriefLoadingSkeleton />;
  }
  if (briefQ.isError || !briefQ.data) {
    return (
      <div className="p-12 text-red-700">
        Failed to load brief: {String((briefQ.error as Error)?.message ?? "unknown")}
      </div>
    );
  }

  const brief = briefQ.data;
  return (
    <div className="min-h-screen bg-slate-50 print:bg-white">
      <PrintStyles />
      <ExportToolbar brief={brief} />
      <article className="brief mx-auto my-8 max-w-3xl bg-white p-10 shadow-sm print:my-0 print:shadow-none print:max-w-none">
        <Header brief={brief} />
        <AtAGlance brief={brief} />
        <WhyGoing brief={brief} />
        <Attendees brief={brief} conferenceId={id} />
        <CfpInfo brief={brief} />
        <PastEngagement brief={brief} />
        <TalkingPoints brief={brief} />
        <Logistics conferenceId={id} brief={brief} />
        <Footer brief={brief} />
      </article>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sections
// ---------------------------------------------------------------------------
function Header({ brief }: { brief: ConferenceBrief }) {
  const h = brief.header;
  const where = [h.location_city, h.location_country].filter(Boolean).join(", ");
  return (
    <header className="mb-6 border-b pb-4">
      <h1 className="text-3xl font-semibold leading-tight">{h.name}</h1>
      <div className="mt-2 text-sm text-slate-600">
        {h.start_date}
        {h.end_date && h.end_date !== h.start_date ? ` – ${h.end_date}` : ""}
        {where ? ` · ${where}` : ""}
        {h.is_virtual ? " · Virtual" : ""}
        {h.venue ? ` · ${h.venue}` : ""}
      </div>
      {h.website && (
        <a
          className="text-sm text-blue-700 underline print:text-black"
          href={h.website}
          target="_blank"
          rel="noopener noreferrer"
        >
          {h.website}
        </a>
      )}
    </header>
  );
}

function AtAGlance({ brief }: { brief: ConferenceBrief }) {
  const g = brief.at_a_glance;
  return (
    <Section title="At a glance">
      <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
        <Bar label="Overall" value={g.overall_score} bucket={g.overall_bucket} />
        <Stat label="Status" value={g.status} />
        <Bar label="Fit" value={g.fit_score} />
        <Stat label="Acceptance rate" value={pct(g.acceptance_rate_percent)} />
        <Bar label="Speakers" value={g.speaker_score} />
        <Stat label="Est. cost" value={g.estimated_cost_usd ? `$${g.estimated_cost_usd}` : "—"} />
        <Stat
          label="Series history"
          value={
            g.series
              ? `Edition of ${g.series.canonical_name} · team attended ${g.series.team_attended_recent} of past ${g.series.past_editions_count}`
              : "—"
          }
        />
      </div>
    </Section>
  );
}

function WhyGoing({ brief }: { brief: ConferenceBrief }) {
  const w = brief.why;
  return (
    <Section title="Why we're going">
      {w.rationale_text ? (
        <p className="text-sm leading-relaxed text-slate-700">{w.rationale_text}</p>
      ) : (
        <Empty>
          Rationale couldn't be generated — usually means there are no
          messaging documents to compare against. Add one on /messaging.
        </Empty>
      )}
      {w.matched_pillar && (
        <p className="mt-2 text-xs text-slate-500">
          <span className="font-medium">Pillar:</span> {w.matched_pillar.name}
        </p>
      )}
      {w.top_topics.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {w.top_topics.map((t) => (
            <span
              key={t.name}
              className="rounded border px-2 py-0.5 text-xs text-slate-700"
            >
              {t.name}
            </span>
          ))}
        </div>
      )}
    </Section>
  );
}

function Attendees({
  brief,
}: {
  brief: ConferenceBrief;
  conferenceId: string;
}) {
  const a = brief.attendees;
  return (
    <Section
      title="Who is going"
    >
      {a.members.length === 0 ? (
        <Empty>
          Nobody recorded yet. Add who is attending from the conference
          page — this section shows the people actually going, not a
          suggestion.
        </Empty>
      ) : (
        <ul className="space-y-3">
          {a.members.map((m, i) => (
            <li key={`${m.person_label}-${m.activity}-${i}`} className="rounded border p-3">
              <div className="flex items-baseline justify-between">
                <span className="text-sm font-semibold">{m.person_label}</span>
                <span className="text-xs text-slate-500">
                  {m.activity}
                  {m.has_attended ? " · attended" : " · planned"}
                </span>
              </div>
              {m.arrives_on && m.departs_on ? (
                <p className="mt-1 text-xs text-slate-500">
                  {m.arrives_on} to {m.departs_on}
                </p>
              ) : null}
              {m.notes ? (
                <p className="mt-1 text-sm text-slate-700">{m.notes}</p>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

function CfpInfo({ brief }: { brief: ConferenceBrief }) {
  const c = brief.cfp;
  return (
    <Section title="CFP">
      {c.deadlines.length === 0 ? (
        <Empty>No CFP deadlines recorded.</Empty>
      ) : (
        <ul className="space-y-1 text-sm">
          {c.deadlines.map((d, i) => (
            <li
              key={`${d.kind}-${i}`}
              className={d.is_next ? "font-semibold" : "text-slate-700"}
            >
              <span className="inline-block w-28 text-slate-500">{d.kind}</span>
              {d.date ?? "TBD"}
              {d.days_remaining !== null
                ? ` · ${d.days_remaining >= 0 ? `${d.days_remaining}d remaining` : `${-d.days_remaining}d ago`}`
                : ""}
              {d.description ? ` · ${d.description}` : ""}
            </li>
          ))}
        </ul>
      )}
      {c.topics_of_interest.length > 0 && (
        <div className="mt-2">
          <div className="text-xs font-medium text-slate-500">Topics of interest</div>
          <div className="mt-1 flex flex-wrap gap-1">
            {c.topics_of_interest.map((t) => (
              <span key={t} className="rounded border px-2 py-0.5 text-xs text-slate-700">
                {t}
              </span>
            ))}
          </div>
        </div>
      )}
    </Section>
  );
}

function PastEngagement({ brief }: { brief: ConferenceBrief }) {
  if (brief.past_engagement.length === 0) {
    return (
      <Section title="Past team engagement">
        <Empty>No prior team attendance recorded for this series.</Empty>
      </Section>
    );
  }
  return (
    <Section title="Past team engagement">
      <ul className="space-y-1 text-sm">
        {brief.past_engagement.map((p) => (
          <li key={`${p.name}-${p.year}`}>
            <span className="font-medium">
              {p.name} ({p.year})
            </span>
            {p.role ? ` · ${p.role}` : ""}
            {p.attendees.length > 0
              ? ` · ${p.attendees.map((a) => a.full_name).join(", ")}`
              : ""}
            {p.notes ? (
              <div className="text-xs text-slate-600">{p.notes}</div>
            ) : null}
          </li>
        ))}
      </ul>
    </Section>
  );
}

function TalkingPoints({ brief }: { brief: ConferenceBrief }) {
  if (brief.talking_points.length === 0) {
    return (
      <Section title="Talking points">
        <Empty>
          No active messaging documents matched. Add one in{" "}
          <Link to="/messaging" className="text-blue-700 underline">
            /messaging
          </Link>{" "}
          to seed talking points.
        </Empty>
      </Section>
    );
  }
  return (
    <Section title="Talking points">
      <ul className="space-y-3 text-sm">
        {brief.talking_points.map((d) => (
          <li key={d.document_id}>
            <div className="font-medium">{d.title}</div>
            <div className="text-sm text-slate-700">{d.elevator_pitch}</div>
            {d.talking_points.length > 0 && (
              <ul className="mt-1 list-disc pl-5 text-xs">
                {d.talking_points.map((p, i) => (
                  <li key={i}>{p}</li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ul>
    </Section>
  );
}

function Logistics({
  conferenceId,
  brief,
}: {
  conferenceId: string;
  brief: ConferenceBrief;
}) {
  const qc = useQueryClient();
  const [draft, setDraft] = useState(brief.logistics);
  const [saved, setSaved] = useState(false);

  // Persisted per conference, shared with the team. These four fields
  // used to live in localStorage under a key the BACKEND computed, so
  // they were visible to one person on one machine and vanished on a
  // cache clear — for four facts the team most needs to share.
  const save = useMutation({
    mutationFn: async () => {
      const res = await fetch(`/api/v1/conferences/${conferenceId}`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          logistics_travel: draft.travel,
          logistics_lodging: draft.lodging,
          logistics_booth: draft.booth,
          logistics_sponsorship: draft.sponsorship,
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    },
    onSuccess: () => {
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
      qc.invalidateQueries({ queryKey: ["conferences", conferenceId, "brief"] });
    },
  });

  const field = (
    key: keyof typeof draft,
    label: string,
  ) => (
    <label className="block">
      <span className="text-xs font-medium text-slate-600">{label}</span>
      <textarea
        className="mt-1 w-full min-h-[3rem] rounded border p-2 text-sm print:border-0 print:p-0"
        value={draft[key]}
        onChange={(e) => setDraft({ ...draft, [key]: e.target.value })}
        spellCheck={false}
      />
    </label>
  );

  return (
    <Section title="Logistics">
      <div className="space-y-2">
        {field("travel", "Travel")}
        {field("lodging", "Lodging")}
        {field("booth", "Swag / booth")}
        {field("sponsorship", "Sponsorship status")}
        <div className="flex items-center gap-2 print:hidden">
          <Button size="sm" onClick={() => save.mutate()} disabled={save.isPending}>
            {save.isPending ? "Saving…" : "Save"}
          </Button>
          {saved && <span className="text-xs text-slate-500">Saved</span>}
        </div>
      </div>
    </Section>
  );
}

function Footer({ brief }: { brief: ConferenceBrief }) {
  return (
    <footer className="mt-8 border-t pt-3 text-xs text-slate-500">
      <div>
        Generated by Scout {brief.scout_version} on{" "}
        {new Date(brief.generated_at).toLocaleString()} ·{" "}
        <a
          className="underline"
          href={brief.footer.detail_url_path}
          target="_blank"
          rel="noopener noreferrer"
        >
          View in Scout
        </a>
      </div>
      {brief.footer.decision && (
        <div className="mt-1">
          Decision: <strong>{brief.footer.decision.decision}</strong> by{" "}
          {brief.footer.decision.decided_by_label || "unknown"}
          {brief.footer.decision.reason ? ` — ${brief.footer.decision.reason}` : ""}
        </div>
      )}
      <div>Sources contributing: {brief.footer.sources_count}</div>
    </footer>
  );
}

// ---------------------------------------------------------------------------
// Toolbar + helpers
// ---------------------------------------------------------------------------
function ExportToolbar({
  brief,
}: {
  brief: ConferenceBrief;
}) {
  const [copied, setCopied] = useState<string | null>(null);

  const copyMarkdown = async () => {
    await navigator.clipboard.writeText(briefToMarkdown(brief));
    setCopied("md");
    setTimeout(() => setCopied(null), 1200);
  };
  const copyHtml = async () => {
    const html = briefToHtml(brief);
    if ("ClipboardItem" in window) {
      try {
        const item = new ClipboardItem({
          "text/html": new Blob([html], { type: "text/html" }),
          "text/plain": new Blob([briefToMarkdown(brief)], { type: "text/plain" }),
        });
        await navigator.clipboard.write([item]);
      } catch {
        await navigator.clipboard.writeText(html);
      }
    } else {
      await navigator.clipboard.writeText(html);
    }
    setCopied("html");
    setTimeout(() => setCopied(null), 1200);
  };

  return (
    <div className="brief-toolbar mx-auto flex max-w-3xl items-center justify-between gap-2 px-4 pt-4 print:hidden">
        <div />
      <div className="flex gap-2">
        <Button size="sm" variant="outline" onClick={copyMarkdown}>
          {copied === "md" ? "Copied!" : "Copy as Markdown"}
        </Button>
        <Button size="sm" variant="outline" onClick={copyHtml}>
          {copied === "html" ? "Copied!" : "Copy as HTML"}
        </Button>
        <Button size="sm" onClick={() => window.print()}>
          Print / Save PDF
        </Button>
      </div>
    </div>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="mb-5">
      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
        {title}
      </h2>
      {children}
    </section>
  );
}

function Bar({
  label,
  value,
  bucket,
}: {
  label: string;
  value: number | null;
  bucket?: ConferenceBrief["at_a_glance"]["overall_bucket"];
}) {
  const pctVal = value == null ? 0 : Math.round(value * 100);
  return (
    <div>
      <div className="flex justify-between text-xs text-slate-600">
        <span>{label}</span>
        <span>
          {value == null ? "—" : pctVal}
          {bucket ? ` · ${bucket}` : ""}
        </span>
      </div>
      <div className="mt-1 h-1.5 w-full rounded bg-slate-200">
        <div
          className="h-full rounded bg-slate-900 print:bg-black"
          style={{ width: `${pctVal}%` }}
        />
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string | null }) {
  return (
    <div>
      <div className="text-xs text-slate-500">{label}</div>
      <div className="text-sm">{value ?? "—"}</div>
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="text-sm italic text-slate-500">{children}</p>;
}

function pct(n: number | null): string | null {
  return n == null ? null : `${n}%`;
}

// ---------------------------------------------------------------------------
// Markdown / HTML export
// ---------------------------------------------------------------------------
function briefToMarkdown(b: ConferenceBrief): string {
  const lines: string[] = [];
  lines.push(`# ${b.header.name}`);
  if (b.header.start_date) {
    const where = [b.header.location_city, b.header.location_country]
      .filter(Boolean)
      .join(", ");
    lines.push(
      `_${b.header.start_date}${b.header.end_date && b.header.end_date !== b.header.start_date ? `–${b.header.end_date}` : ""}${where ? ` · ${where}` : ""}_`,
    );
  }
  if (b.header.website) lines.push(`<${b.header.website}>`);
  lines.push("");

  const g = b.at_a_glance;
  lines.push("## At a glance");
  lines.push(
    `- Overall: **${g.overall_score == null ? "—" : Math.round(g.overall_score * 100)}** (${g.overall_bucket ?? "—"})`,
  );
  lines.push(
    `- Fit: ${g.fit_score == null ? "—" : Math.round(g.fit_score * 100)} · Speakers: ${g.speaker_score == null ? "—" : Math.round(g.speaker_score * 100)}`,
  );
  if (g.acceptance_rate_percent != null)
    lines.push(`- Acceptance rate: ${g.acceptance_rate_percent}%`);
  if (g.estimated_cost_usd != null) lines.push(`- Est. cost: $${g.estimated_cost_usd}`);
  lines.push("");

  if (b.why.rationale_text) {
    lines.push("## Why we're going");
    lines.push(b.why.rationale_text);
    lines.push("");
  }

  if (b.attendees.members.length) {
    lines.push("## Who is going");
    for (const m of b.attendees.members) {
      const when =
        m.arrives_on && m.departs_on ? ` — ${m.arrives_on} to ${m.departs_on}` : "";
      lines.push(`- **${m.person_label}** (${m.activity}${when})`);
    }
    lines.push("");
  }

  if (b.cfp.deadlines.length) {
    lines.push("## CFP");
    for (const d of b.cfp.deadlines) {
      lines.push(
        `- ${d.is_next ? "**" : ""}${d.kind ?? "deadline"}: ${d.date ?? "TBD"}${d.days_remaining != null ? ` (${d.days_remaining}d)` : ""}${d.is_next ? "**" : ""}`,
      );
    }
    lines.push("");
  }

  if (b.talking_points.length) {
    lines.push("## Talking points");
    for (const t of b.talking_points) {
      lines.push(`**${t.title}** — ${t.elevator_pitch}`);
      for (const p of t.talking_points) lines.push(`- ${p}`);
    }
    lines.push("");
  }

  lines.push(`_Generated by Scout ${b.scout_version} on ${b.generated_at}_`);
  return lines.join("\n");
}

function briefToHtml(b: ConferenceBrief): string {
  return briefToMarkdown(b)
    .split("\n")
    .map((line) => {
      if (line.startsWith("# ")) return `<h1>${escapeHtml(line.slice(2))}</h1>`;
      if (line.startsWith("## ")) return `<h2>${escapeHtml(line.slice(3))}</h2>`;
      if (line.startsWith("- "))
        return `<li>${escapeHtml(line.slice(2))}</li>`;
      if (!line.trim()) return "<br/>";
      return `<p>${escapeHtml(line)}</p>`;
    })
    .join("\n");
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ---------------------------------------------------------------------------
// Print stylesheet
// ---------------------------------------------------------------------------
// First-time brief loads can take 20+ seconds because the endpoint
// auto-runs the matcher (and embedding pipeline) when no Match exists
// yet for this conference. A skeleton + a "what's happening" hint beats
// a flat "Loading brief…" string by a lot.
function BriefLoadingSkeleton() {
  return (
    <div className="min-h-screen bg-slate-50">
      <div className="mx-auto my-8 max-w-3xl bg-white p-10 shadow-sm">
        <div className="flex items-center gap-3">
          <span className="inline-block h-3 w-3 animate-pulse rounded-full bg-red-500" />
          <p className="text-sm text-slate-600">
            Running matcher + composing brief…
          </p>
        </div>
        <p className="mt-2 text-xs text-slate-400">
          First open scores the conference against every active SME and
          messaging document. Usually 5–30 seconds; subsequent opens are
          cached.
        </p>
        <div className="mt-8 space-y-6">
          {/* fake header */}
          <div>
            <div className="h-8 w-2/3 animate-pulse rounded bg-slate-200" />
            <div className="mt-2 h-4 w-1/3 animate-pulse rounded bg-slate-100" />
          </div>
          {/* at-a-glance grid */}
          <div className="grid grid-cols-3 gap-3">
            {[0, 1, 2].map((i) => (
              <div key={i} className="h-16 animate-pulse rounded bg-slate-100" />
            ))}
          </div>
          {/* rationale block */}
          <div className="space-y-2">
            <div className="h-3 w-1/4 animate-pulse rounded bg-slate-200" />
            <div className="h-3 w-full animate-pulse rounded bg-slate-100" />
            <div className="h-3 w-5/6 animate-pulse rounded bg-slate-100" />
            <div className="h-3 w-3/4 animate-pulse rounded bg-slate-100" />
          </div>
          {/* attendee rows */}
          {[0, 1].map((i) => (
            <div key={i} className="rounded border border-slate-100 p-3">
              <div className="h-4 w-1/3 animate-pulse rounded bg-slate-200" />
              <div className="mt-2 h-3 w-2/3 animate-pulse rounded bg-slate-100" />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function PrintStyles() {
  return (
    <style>{`
      @media print {
        @page { size: A4; margin: 0.5in; }
        body { background: white !important; }
        .brief-toolbar { display: none !important; }
        nav, aside, [data-print-hide] { display: none !important; }
        a { color: inherit; text-decoration: none; }
        .brief { box-shadow: none; padding: 0; }
        section { page-break-inside: avoid; }
      }
    `}</style>
  );
}
