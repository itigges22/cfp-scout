/**
 * /settings/tutorial — interactive documentation for the SCOUT platform.
 *
 * Layout mirrors Google/MDN docs: sticky left-rail table-of-contents whose
 * active item tracks scroll position via IntersectionObserver, with
 * full-width prose content on the right. No external deps beyond what the
 * app already ships.
 */

import { useEffect, useRef, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/settings_/tutorial")({
  component: TutorialPage,
});

// ---------------------------------------------------------------------------
// Section registry — single source of truth for the ToC and the content.
//
// Was thirteen sections and ~800 lines, much of it describing a matcher that
// no longer exists (Stage A/B/C/D) and five settings that were never real.
// Five sections now. Everything here is checked against the running app.
// ---------------------------------------------------------------------------

const SECTIONS = [
  { id: "start", label: "Start here" },
  { id: "scoring", label: "How scoring works" },
  { id: "pages", label: "The pages" },
  { id: "settings", label: "Settings worth knowing" },
  { id: "wrong", label: "When it looks wrong" },
] as const;

function TutorialPage() {
  const [active, setActive] = useState<string>(SECTIONS[0].id);
  const observerRef = useRef<IntersectionObserver | null>(null);

  useEffect(() => {
    observerRef.current?.disconnect();
    const obs = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible[0]?.target.id) setActive(visible[0].target.id);
      },
      { rootMargin: "-80px 0px -70% 0px", threshold: 0 },
    );
    for (const { id } of SECTIONS) {
      const el = document.getElementById(id);
      if (el) obs.observe(el);
    }
    observerRef.current = obs;
    return () => obs.disconnect();
  }, []);

  const scrollTo = (id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return (
    <div className="flex min-h-screen gap-8">
      <aside className="sticky top-4 hidden h-fit w-48 shrink-0 lg:block xl:w-56">
        <p className="mb-3 text-xs font-semibold uppercase tracking-widest text-fg-muted">
          On this page
        </p>
        <nav className="flex flex-col gap-0.5">
          {SECTIONS.map(({ id, label }) => (
            <button
              key={id}
              onClick={() => scrollTo(id)}
              className={[
                "rounded px-2 py-1 text-left text-sm transition-colors",
                active === id
                  ? "bg-accent/15 font-medium text-accent"
                  : "text-fg-muted hover:bg-surface-2 hover:text-fg",
              ].join(" ")}
            >
              {label}
            </button>
          ))}
        </nav>
      </aside>

      <article className="max-w-3xl flex-1 pb-24">
        <h1 className="mb-2 text-3xl font-semibold tracking-tight">How Scout works</h1>
        <p className="mb-8 text-sm leading-relaxed text-fg-muted">
          Scout finds conferences, scores them against what your team actually
          does, and tracks what you decided and what came of it.
        </p>

        <Section id="start" title="Start here">
          <Callout kind="warning">
            Scout scores conferences by comparing them to <strong>your</strong>{" "}
            material. With none loaded, every conference scores zero and lands in{" "}
            <Chip color="yellow">low messaging fit</Chip>. That is not a bug — there
            is nothing to compare against yet.
          </Callout>

          <H3>Do these three, in order</H3>
          <Ol>
            <li>
              <strong>Messaging</strong> — upload your positioning documents. This
              is the single highest-impact step: it is half of every score.
            </li>
            <li>
              <strong>Pillars</strong> — the few strategic themes you care about.
              Create them from the sidebar. Pillars are the other half.
            </li>
            <li>
              <strong>SMEs</strong> — who could speak, with a real bio. Link each
              one to the pillars they cover.
            </li>
          </Ol>
          <P>
            Everything else is optional. Talks sharpen the speaker score; audiences
            and topics sharpen SME ranking. Discovery runs on its own.
          </P>

          <H3>Then</H3>
          <P>
            Open <strong>Conferences</strong>. Approve or reject. Record who is
            going. After the event, add what it cost and what it produced — that is
            what makes &ldquo;was it worth it&rdquo; answerable next year.
          </P>
        </Section>

        <Section id="scoring" title="How scoring works">
          <P>Two questions, not four. Each produces a number in [0, 1].</P>
          <Dl>
            <dt className="font-mono text-xs text-accent">fit</dt>
            <dd className="text-fg-muted">
              Do they care about what we do? Conference text against your messaging
              documents <em>and</em> your pillars, pooled into one number.
            </dd>
            <dt className="font-mono text-xs text-accent">speakers</dt>
            <dd className="text-fg-muted">
              Can we show up well? Conference text against SME bios <em>and</em> the
              talks those people can give.
            </dd>
          </Dl>
          <Code>{`overall = 0.65 x fit + 0.35 x speakers
          + boosts (CFP closing soon, series we liked before)
          - penalties (attended recently)
          then the judge can veto it outright`}</Code>

          <H3>The judge is a veto, not a score</H3>
          <P>
            Embeddings measure vocabulary, not audience. A marketing summit can use
            all the right words. So an LLM reads each conference and can reject it
            regardless of how high it scored. Its verdict is cached against a hash
            of its inputs — edit the prompt and every cached verdict is recomputed.
          </P>

          <H3>Two gates decide the status</H3>
          <Dl>
            <dt className="font-mono text-xs">MATCH_M_GATE</dt>
            <dd className="text-fg-muted">
              Below it: <Chip color="yellow">low messaging fit</Chip>, hidden from
              the default view. This is the setting that makes conferences seem to
              vanish.
            </dd>
            <dt className="font-mono text-xs">MATCH_S_GATE</dt>
            <dd className="text-fg-muted">
              Below it: <Chip color="blue">needs SME review</Chip>. Lower than the
              fit gate, because SME data is usually sparser.
            </dd>
          </Dl>
          <Callout kind="info">
            A ranking dimension with no measurable input is <strong>dropped</strong>{" "}
            and the rest renormalised — not scored as a real zero. Scoring it zero
            would cap every candidate below the gate and the gate would stop meaning
            what it says.
          </Callout>
        </Section>

        <Section id="pages" title="The pages">
          <Dl>
            <dt className="font-semibold">Dashboard</dt>
            <dd className="text-fg-muted">
              Totals and a world map. Pins need coordinates — see below if it is empty.
            </dd>
            <dt className="font-semibold">Conferences</dt>
            <dd className="text-fg-muted">
              The working list. Filter by status, location, our involvement; sort by
              score or CFP deadline. Closed CFPs are hidden unless you are going.
            </dd>
            <dt className="font-semibold">SMEs</dt>
            <dd className="text-fg-muted">
              Your speakers. Bio quality drives match quality — the 200-character
              minimum is deliberate, since short bios embed badly.
            </dd>
            <dt className="font-semibold">Talks</dt>
            <dd className="text-fg-muted">
              What your people can present. Start one from a document or from scratch.
            </dd>
            <dt className="font-semibold">Messaging</dt>
            <dd className="text-fg-muted">
              Your positioning documents. Upload a PDF and the LLM extracts the
              claims, or type them in.
            </dd>
            <dt className="font-semibold">Pillars</dt>
            <dd className="text-fg-muted">
              In the sidebar. Each has its own audiences and linked SMEs.
            </dd>
            <dt className="font-semibold">Topics</dt>
            <dd className="text-fg-muted">
              Auto-extracted vocabulary. You approve or deactivate — you do not
              create them. Topic overlap is one of the five SME ranking dimensions.
            </dd>
            <dt className="font-semibold">Diagnostics</dt>
            <dd className="text-fg-muted">
              Is anything broken, and what has it cost? LLM connectivity, spend,
              job and scraper health.
            </dd>
          </Dl>
        </Section>

        <Section id="settings" title="Settings worth knowing">
          <P>
            Every setting is live — no restart, no redeploy. A value you set here
            beats the environment variable behind it.
          </P>
          <Dl>
            <dt className="font-mono text-xs">llm_api_key</dt>
            <dd className="text-fg-muted">
              Entered here, never in config. Masked after saving; paste a new one to
              rotate.
            </dd>
            <dt className="font-mono text-xs">Prompts</dt>
            <dd className="text-fg-muted">
              Every LLM prompt is editable — the judge, the rationale, extraction,
              enrichment. Keep <code>{"{operator_profile}"}</code> in the judge
              prompt or your own description of what you care about is dropped.
            </dd>
            <dt className="font-mono text-xs">discovery_keywords</dt>
            <dd className="text-fg-muted">
              The biggest lever on what gets found. A handful is enough — each one
              expands into many queries.
            </dd>
            <dt className="font-mono text-xs">MATCH_W_FIT / MATCH_W_SPEAKERS</dt>
            <dd className="text-fg-muted">Must sum to 1.0. Defaults 0.65 / 0.35.</dd>
            <dt className="font-mono text-xs">SME_W_*</dt>
            <dd className="text-fg-muted">
              The five SME dimensions. Must sum to exactly 1.0.
            </dd>
          </Dl>
        </Section>

        <Section id="wrong" title="When it looks wrong">
          <Dl>
            <dt className="font-semibold">Everything is &ldquo;low messaging fit&rdquo;</dt>
            <dd className="text-fg-muted">
              No messaging documents or no pillars. The fit half of every score has
              nothing to compare against. Load them and re-run the matcher.
            </dd>
            <dt className="font-semibold">The map is empty</dt>
            <dd className="text-fg-muted">
              Conferences have no coordinates. Trigger the geocode backfill
              (POST /api/v1/admin/discovery/geocode-backfill) — it queues a
              background job you can watch under Diagnostics. Geocoding needs a
              real <code>scraper_user_agent</code>; OpenStreetMap rejects
              placeholder contact details outright.
            </dd>
            <dt className="font-semibold">The list looks short</dt>
            <dd className="text-fg-muted">
              Closed CFPs are hidden by default, and so are grassroot events. Both
              have toggles.
            </dd>
            <dt className="font-semibold">A conference you expected is missing</dt>
            <dd className="text-fg-muted">
              Check <Chip color="yellow">low messaging fit</Chip> in the status
              filter, or that its CFP has not already closed.
            </dd>
            <dt className="font-semibold">Nothing is being discovered</dt>
            <dd className="text-fg-muted">
              Check <code>discovery_enabled</code>, then Diagnostics for scraper and
              LLM errors.
            </dd>
            <dt className="font-semibold">Saving something does nothing</dt>
            <dd className="text-fg-muted">
              Forms block on required fields and say which. A bio under 200
              characters is the usual one.
            </dd>
          </Dl>
        </Section>
      </article>
    </div>
  );
}

function Section({
  id,
  title,
  children,
}: {
  id: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className="mb-16 scroll-mt-6">
      <h2 className="mb-4 border-b border-border pb-2 text-2xl font-semibold">{title}</h2>
      <div className="flex flex-col gap-4">{children}</div>
    </section>
  );
}

function H3({ children }: { children: React.ReactNode }) {
  return <h3 className="mt-4 text-base font-semibold text-fg">{children}</h3>;
}

function P({ children }: { children: React.ReactNode }) {
  return <p className="text-sm leading-relaxed text-fg-muted">{children}</p>;
}


function Ol({ children }: { children: React.ReactNode }) {
  return <ol className="list-decimal space-y-1.5 pl-5 text-sm text-fg-muted">{children}</ol>;
}

function Dl({ children }: { children: React.ReactNode }) {
  return <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-2 text-sm">{children}</dl>;
}

function Code({ children }: { children: React.ReactNode }) {
  return (
    <pre className="overflow-x-auto rounded-md border border-border bg-surface-2 p-4 font-mono text-xs leading-relaxed text-fg">
      {children}
    </pre>
  );
}

function Callout({
  kind,
  children,
}: {
  kind: "info" | "warning";
  children: React.ReactNode;
}) {
  const styles =
    kind === "warning"
      ? "border-warning/40 bg-warning/10 text-warning"
      : "border-accent/30 bg-accent/10 text-accent";
  return (
    <div className={`rounded-md border p-3 text-sm leading-relaxed ${styles}`}>{children}</div>
  );
}

function Chip({ color, children }: { color: "green" | "yellow" | "blue"; children: React.ReactNode }) {
  const c =
    color === "green"
      ? "bg-success/20 text-success"
      : color === "yellow"
        ? "bg-warning/20 text-warning"
        : "bg-accent/20 text-accent";
  return <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${c}`}>{children}</span>;
}
