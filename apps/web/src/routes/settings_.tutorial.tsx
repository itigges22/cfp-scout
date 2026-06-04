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
// ---------------------------------------------------------------------------

const SECTIONS = [
  { id: "overview",      label: "Overview" },
  { id: "dashboard",     label: "Dashboard & Map" },
  { id: "conferences",   label: "Conferences" },
  { id: "matcher",       label: "Matching Pipeline" },
  { id: "boosts",        label: "Score Boosts" },
  { id: "pillars",       label: "Strategic Pillars" },
  { id: "smes",          label: "SME Profiles" },
  { id: "talks",         label: "Talks Library" },
  { id: "audiences",     label: "Audience Profiles" },
  { id: "past",          label: "Past Conferences" },
  { id: "topics",        label: "Topics" },
  { id: "settings",      label: "Settings & Tunables" },
  { id: "workflows",     label: "Common Workflows" },
] as const;

type SectionId = (typeof SECTIONS)[number]["id"];

// ---------------------------------------------------------------------------
// Page shell
// ---------------------------------------------------------------------------

function TutorialPage() {
  const [active, setActive] = useState<SectionId>("overview");
  const observerRef = useRef<IntersectionObserver | null>(null);

  useEffect(() => {
    const entries = new Map<string, IntersectionObserverEntry>();

    observerRef.current = new IntersectionObserver(
      (observed) => {
        for (const e of observed) entries.set(e.target.id, e);
        // Pick the topmost visible section
        const visible = [...entries.values()]
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        const first = visible[0];
        if (first) setActive(first.target.id as SectionId);
      },
      { rootMargin: "-20% 0px -60% 0px", threshold: 0 },
    );

    for (const { id } of SECTIONS) {
      const el = document.getElementById(id);
      if (el) observerRef.current.observe(el);
    }
    return () => observerRef.current?.disconnect();
  }, []);

  const scrollTo = (id: SectionId) => {
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return (
    <div className="flex min-h-screen gap-8">
      {/* ---- Left sidebar ToC ---- */}
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

      {/* ---- Main content ---- */}
      <article className="max-w-3xl flex-1 pb-24">
        <div className="mb-8 rounded-lg border border-accent/20 bg-accent/5 px-4 py-3 text-sm leading-relaxed text-fg-muted">
          End-to-end reference for the SCOUT platform. Use the table of contents on the left to
          jump to any topic. For the short version of any concept, hover over the{" "}
          <strong>?</strong> icons throughout the app. For the interactive version, use{" "}
          <strong>Agent chat</strong> and just ask.
        </div>
        <Section id="overview" title="Overview">
          <P>
            <strong>SCOUT</strong> is a conference intelligence and speaker-matching platform built
            for DevRel and go-to-market teams. It answers two questions for every conference that
            comes across your radar:
          </P>
          <Ol>
            <li>
              <strong>Is this conference worth our time?</strong> — scored by how well the event
              aligns with your messaging, strategic pillars, and SME roster.
            </li>
            <li>
              <strong>Who should we send?</strong> — ranked by topic overlap, bio similarity,
              location, and past attendance history.
            </li>
          </Ol>
          <P>
            Everything flows through a four-stage matching pipeline. The scores feed a dashboard
            where you approve, archive, or queue conferences for review. Approved conferences show
            up with SME recommendations and an AI-written rationale brief.
          </P>
          <Callout kind="info">
            SCOUT does not contact conferences, register speakers, or send emails. It is a
            decision-support tool: it surfaces candidates and scores, but humans make the calls.
          </Callout>
        </Section>

        <Section id="dashboard" title="Dashboard & Map">
          <P>
            The dashboard is the main entry point. It shows a world map with color-coded
            conference markers and a card list below.
          </P>
          <H3>Map markers</H3>
          <Ul>
            <li>
              <Chip color="green">Green</Chip> — conferences you or a past team has attended
              (pulled from Past Conferences).
            </li>
            <li>
              <Chip color="yellow">Yellow</Chip> — same series as a past conference (e.g. KubeCon
              EU when you attended KubeCon NA).
            </li>
            <li>
              <Chip color="blue">Blue (default)</Chip> — standard match, no attendance history.
            </li>
          </Ul>
          <P>
            Click any marker or card to open the conference detail page, which shows the score
            breakdown, rationale brief, SME recommendations, and submission history.
          </P>
          <H3>Status filters</H3>
          <P>
            The card list can be filtered by matcher status. Each status maps to what the pipeline
            decided:
          </P>
          <Dl>
            <dt>approved</dt>
            <dd>All three gates cleared + boosts applied. Review and decide.</dd>
            <dt>needs_review_pillar</dt>
            <dd>Messaging fit passed but pillar alignment was weak. Check which pillar it might
              fit or adjust the pillar descriptions.</dd>
            <dt>needs_sme_review</dt>
            <dd>Messaging + pillar fit passed but no SME scored above the SME gate. You may need
              to add more topic tags to relevant SMEs.</dd>
            <dt>low_messaging_fit</dt>
            <dd>The conference text is not sufficiently similar to your messaging documents. It
              probably isn't worth the team's time, but you can still manually approve.</dd>
            <dt>discovered / needs_review</dt>
            <dd>Freshly scraped, not yet matched. Run the matcher from Settings → Maintenance.</dd>
            <dt>quarantined</dt>
            <dd>Blocked from matching (scraper flagged low confidence or admin quarantine). Hidden
              from the default list.</dd>
          </Dl>
        </Section>

        <Section id="conferences" title="Conferences">
          <P>
            Conferences are the core objects in SCOUT. Each one has a name, dates, location, CFP
            deadline, a topic set, and an audience set — all of which feed the matcher.
          </P>
          <H3>How conferences get in</H3>
          <Ol>
            <li>
              <strong>Scraper pipeline</strong> — the background scheduler discovers events from
              configured sources and writes them with status <code>discovered</code>.
            </li>
            <li>
              <strong>Manual entry</strong> — use the "New conference" button on the Conferences
              page.
            </li>
            <li>
              <strong>Workbook import</strong> — bulk-import via the XLSX template (Settings →
              Workbook).
            </li>
          </Ol>
          <H3>Conference detail page</H3>
          <P>Each conference detail page has four tabs:</P>
          <Ul>
            <li>
              <strong>Brief</strong> — AI-generated rationale: why this conference fits (or
              doesn't), which pillar it best aligns with, and top SME narratives.
            </li>
            <li>
              <strong>Match details</strong> — the four stage scores (messaging / pillar / SME /
              judge), per-pillar breakdown, boost breakdown, and the full SME rank table.
            </li>
            <li>
              <strong>Edit</strong> — fields, topic tags, audience tags.
            </li>
            <li>
              <strong>Submissions</strong> — track which talks were submitted to this conference
              and their outcomes.
            </li>
          </Ul>
          <H3>Decision flow</H3>
          <P>
            From the conference page, you can <strong>Approve</strong> (commit to attending),
            <strong>Archive</strong> (not this year), or leave it in the queue. Approvals feed the
            series-memory boost so future editions of the same conference series rank higher
            automatically.
          </P>
        </Section>

        <Section id="matcher" title="Matching Pipeline">
          <P>
            The matcher runs four stages in sequence. Each stage produces a score in [0, 1]. The
            overall score is a weighted average; the pipeline re-normalizes weights so they always
            sum correctly even when a stage is disabled.
          </P>
          <H3>Stage A — Messaging fit</H3>
          <P>
            Compares the conference's text chunks against your active messaging documents using
            cosine similarity (nomic-embed-text) blended with a lexical keyword-overlap signal.
            The blend ratio is 55% embedding / 45% lexical — the lexical signal compensates for
            the embedder's tendency to collapse short-form event descriptions into a tight cosine
            band.
          </P>
          <P>
            If a conference has no embedding chunks (extraction failed), Stage A returns 0.0 and
            the conference will land in <code>low_messaging_fit</code>. Re-run the scraper or
            manually trigger embedding from the admin API.
          </P>
          <P>
            <strong>Gate:</strong> <code>MATCH_M_GATE</code> (default 0.55). Conferences below
            this gate get status <code>low_messaging_fit</code> unless the LLM judge overrides.
          </P>
          <H3>Stage B — Pillar alignment</H3>
          <P>
            For each strategic pillar, SCOUT computes the cosine between the conference chunks and
            the pillar's text (using its enriched description when available, falling back to the
            plain description). The per-pillar scores are transformed through a softmax
            "peakedness" function — a conference that strongly peaks on one pillar scores higher
            than one that weakly matches all pillars equally (which usually indicates generic
            AI-adjacent content rather than true alignment).
          </P>
          <P>
            <strong>Gate:</strong> <code>MATCH_P_GATE</code> (default 0.55).
          </P>
          <H3>Stage C — SME match</H3>
          <P>
            Ranks every active SME against the conference on five dimensions (see SME Profiles for
            the breakdown). The stage score is the composite score of the top-ranked SME.
          </P>
          <P>
            <strong>Gate:</strong> <code>MATCH_S_GATE</code> (default 0.50).
          </P>
          <H3>Stage D — LLM judge (optional)</H3>
          <P>
            A chat-LLM cross-encoder that reads the conference abstract, your operator profile,
            and the pillar descriptions, then returns a relevance score in [0, 1] and a brief
            rationale. The judge catches two failure modes the embedding stages miss:
          </P>
          <Ul>
            <li>
              <strong>Overrated events</strong> — generic "AI conference" language scores high on
              cosine but the judge reads it as shallow. Judge score below 0.20 vetoes the event
              regardless of stages A–C.
            </li>
            <li>
              <strong>Underrated events</strong> — sparsely-named or niche events (e.g.
              "AgentCon Phoenix") score low on cosine but the judge recognizes them as highly
              relevant. Judge score above 0.70 lifts the conference past the messaging gate.
            </li>
          </Ul>
          <P>
            The judge result is cached by input hash — a re-run with the same conference text,
            pillars, and calibration examples reuses the cached score at zero LLM cost.
          </P>
          <Callout kind="warning">
            The judge uses your <code>OPENAI_API_KEY</code> (or equivalent). Disable it via
            <code>ENABLE_LLM_JUDGE=false</code> to cut cost, especially during bulk rescoring.
          </Callout>
          <H3>Overall score formula</H3>
          <Code>{`overall = (w_msg × A + w_pil × B + w_sme × C + w_judge × D) / total_w
total_w = w_msg + w_pil + w_sme + (w_judge if judge ran else 0)`}</Code>
          <P>
            Default weights: messaging 0.40 · pillar 0.15 · SME 0.20 · judge 0.45. With all four
            stages active (total_w = 1.20) the effective fractions are roughly 33% / 12.5% /
            16.7% / 37.5%. Adjust in Settings → Tunables.
          </P>
        </Section>

        <Section id="boosts" title="Score Boosts">
          <P>
            After the four-stage score is computed, SCOUT applies small additive boosts to reflect
            business-logic signals that semantic similarity can't capture. All boosts are capped
            so they nudge the ranking without overriding it.
          </P>
          <Dl>
            <dt>CFP urgency (+0.10)</dt>
            <dd>
              The CFP deadline is within 30 days. Applied to future-dated conferences only. Use
              this to surface actionable events even when they rank below more-relevant events
              with no open CFP.
            </dd>
            <dt>Series memory (±0.10 / +0.05)</dt>
            <dd>
              If you attended a past edition of this conference series and gave it a verdict:
              <br />— <code>would_attend</code> → +0.10
              <br />— <code>would_not_attend</code> → −0.10
              <br />— <code>unsure</code> → +0.05
              <br />
              No explicit verdict but the series appears in your approved decisions → +0.10.
            </dd>
            <dt>Flagship event (+0.15)</dt>
            <dd>
              The conference name matches a curated list of industry-tier flagships (KubeCon,
              AWS re:Invent, Google Cloud Next, NVIDIA GTC, etc.). Community satellite events
              sharing the same brand name (e.g. "Microsoft Build // Localhost:CapeTown") are
              excluded by pattern matching.
            </dd>
            <dt>Recency penalty (−0.05)</dt>
            <dd>
              The conference start date is more than 12 months in the future. Reduces noise from
              distant events that you can't realistically plan for today.
            </dd>
          </Dl>
          <P>
            Each boost can be toggled independently in Settings → Tunables. The total of all
            boosts is clamped to keep the final score in [0, 1].
          </P>
        </Section>

        <Section id="pillars" title="Strategic Pillars">
          <P>
            Strategic pillars are the top-level themes that organize your DevRel strategy. Every
            conference gets aligned to the pillar it best matches (Stage B). Every SME, talk, and
            audience profile can be associated with a pillar.
          </P>
          <H3>Creating and editing pillars</H3>
          <Ul>
            <li>
              In the sidebar, find the Info section. Pillars appear as individual nav items
              between the divider and the "＋ New pillar" button.
            </li>
            <li>
              <strong>Single-click</strong> a pillar to navigate to its detail page.
            </li>
            <li>
              <strong>Double-click</strong> a pillar to open a quick-edit dialog for its name and
              description.
            </li>
            <li>
              Click <strong>＋ New pillar</strong> at the bottom to create one. You will be taken
              directly to the new pillar's page.
            </li>
          </Ul>
          <H3>Pillar detail page tabs</H3>
          <Dl>
            <dt>Overview</dt>
            <dd>Description and AI-enriched description (populated when messaging documents are
              linked to the pillar).</dd>
            <dt>Talks</dt>
            <dd>All active talks assigned to this pillar. Click any row to edit.</dd>
            <dt>SMEs</dt>
            <dd>Link or unlink SMEs from this pillar. Primary-pillar flag marks the SME's main
              area of responsibility.</dd>
            <dt>Audiences</dt>
            <dd>Full audience profile CRUD scoped to this pillar. Create, edit, and delete
              audience personas from here — there is no separate global Audiences page.</dd>
            <dt>Content Roadmap</dt>
            <dd>Quarterly content goals, owners, and notes for this pillar. Freeform planning
              artifact.</dd>
            <dt>GTM Strategy</dt>
            <dd>Versioned go-to-market strategy entries. Each new version gets an auto-incremented
              version number; the previous version is preserved for history.</dd>
          </Dl>
          <Callout kind="info">
            Deleting a pillar removes its SME links and GTM entries (cascade). Talks and audience
            profiles that were assigned to the pillar have their pillar_id set to NULL — they are
            not deleted.
          </Callout>
        </Section>

        <Section id="smes" title="SME Profiles">
          <P>
            Subject matter experts (SMEs) are the speakers and thought leaders your team can send
            to conferences. The matcher ranks them against each conference on five dimensions.
          </P>
          <H3>SME dimensions</H3>
          <Dl>
            <dt>Topic overlap (weight: 30%)</dt>
            <dd>
              Jaccard similarity between the conference's approved topic tags and the SME's topic
              tags. Assign topic tags to SMEs from their edit dialog; the topic list is managed
              under Topics (admin). The higher the tag overlap, the stronger this signal.
            </dd>
            <dt>Audience overlap (weight: 25%)</dt>
            <dd>
              Jaccard similarity between the conference's audience tags and the SME's linked
              audience profiles. Currently 0 for most conferences until audience tags are
              populated via the conference edit form.
            </dd>
            <dt>Bio similarity (weight: 30%)</dt>
            <dd>
              Cosine similarity between the conference text embeddings and the SME bio embeddings.
              Write a detailed bio — the richer the bio text, the more accurately the model can
              match it against conference abstracts.
            </dd>
            <dt>Location proximity (weight: 10%)</dt>
            <dd>
              Virtual conference → 1.0. Same country as the SME → 1.0. Same continent → 0.6.
              Cross-continent → 0.3. Set the SME's country in their profile.
            </dd>
            <dt>Past attendance (weight: 5%)</dt>
            <dd>
              1.0 if the SME has a past_conferences record for the same conference series. Requires
              the conference to have a series_id link (auto-linked on import or via the admin
              series-link endpoint).
            </dd>
          </Dl>
          <H3>Composite score formula</H3>
          <Code>{`composite = topic × 0.30 + audience × 0.25 + bio × 0.30 + location × 0.10 + past × 0.05`}</Code>
          <P>
            These weights are adjustable in Settings → Tunables under "SME ranker weights."
          </P>
          <H3>SME narratives</H3>
          <P>
            For the top 3 SMEs per conference, SCOUT generates a short AI-written narrative
            explaining why they are a good fit. Narratives are cached and regenerated on each
            re-score (unless the input hash matches the previous run). View them on the conference
            brief tab or regenerate from the admin matcher API.
          </P>
        </Section>

        <Section id="talks" title="Talks Library">
          <P>
            The Talks Library tracks all talk abstracts your team has created or is developing.
            Each talk can be submitted to multiple conferences, and SCOUT will warn you about
            reuse risk (submitting the same talk to overlapping conferences).
          </P>
          <H3>Creating talks</H3>
          <Ul>
            <li>
              <strong>Manual:</strong> Click "New talk" on the Talks page. Fill in the title,
              abstract, format, duration, pillar, and review status.
            </li>
            <li>
              <strong>Upload:</strong> Click "Upload document" and select a PDF, TXT, or DOCX
              file. SCOUT uses Docling to extract the text, then runs an LLM extraction pass to
              suggest a title, abstract, format, duration, and pillar. You review the extracted
              fields before saving — nothing is written to the database until you click "Save to
              library."
            </li>
          </Ul>
          <H3>Review status</H3>
          <Dl>
            <dt>draft</dt>
            <dd>Work in progress. Not ready for submission review.</dd>
            <dt>pending_review</dt>
            <dd>Ready for the team to review before submitting to conferences.</dd>
            <dt>approved</dt>
            <dd>Cleared for submission. Shows in the conference submission picker.</dd>
          </Dl>
          <H3>Submissions</H3>
          <P>
            From a conference's Submissions tab, you can record that a talk was submitted and
            track its outcome (accepted, rejected, withdrawn, etc.). SCOUT uses the submission
            history for reuse-risk calculations.
          </P>
        </Section>

        <Section id="audiences" title="Audience Profiles">
          <P>
            Audience profiles describe the personas your messaging targets — who they are, what
            they care about, what their pain points are, and what messages resonate with them.
            Each profile belongs to a specific pillar.
          </P>
          <H3>Managing audiences</H3>
          <P>
            Audiences live exclusively under their pillar. Navigate to a pillar → Audiences tab to
            create, edit, or delete profiles. There is no standalone global Audiences page.
          </P>
          <H3>Fields</H3>
          <Dl>
            <dt>Name</dt>
            <dd>Short label, e.g. "Platform Engineering Lead."</dd>
            <dt>Description</dt>
            <dd>Who this persona is and what they care about (50–500 chars).</dd>
            <dt>Industry</dt>
            <dd>Primary industry vertical.</dd>
            <dt>Role seniority</dt>
            <dd>Executive / Director / Manager / IC / Mixed.</dd>
            <dt>Primary pain points</dt>
            <dd>2–8 bullet-point pain points. Used in messaging briefs.</dd>
            <dt>Key messages</dt>
            <dd>2–8 messages that resonate with this persona.</dd>
          </Dl>
          <P>
            Audience profiles are linked to conferences via the conference edit form (audience
            tags). The SME ranker's "audience overlap" dimension uses these tags.
          </P>
        </Section>

        <Section id="past" title="Past Conferences">
          <P>
            The Past Conferences page is the feedback loop into the matcher. It stores events your
            team has already attended (or considered attending) along with who went and a verdict.
          </P>
          <H3>Verdict system</H3>
          <Dl>
            <dt>would_attend 👍</dt>
            <dd>
              Worth repeating. Adds +0.10 to the series-memory boost for future editions of the
              same series.
            </dd>
            <dt>would_not_attend 👎</dt>
            <dd>
              Not worth it. Adds −0.10 to future editions — pushes them down in the ranking even
              if they score well on semantics.
            </dd>
            <dt>unsure</dt>
            <dd>Default. Adds +0.05 (small positive while the team hasn't decided).</dd>
          </Dl>
          <P>
            The verdict is applied whenever the matcher encounters a future conference whose
            normalized name fuzzy-matches a past record. The matching uses trigram similarity +
            token Jaccard to handle variations like "KubeCon + CloudNativeCon Europe 2027" →
            "KubeCon EU."
          </P>
          <H3>Series linking</H3>
          <P>
            Past conferences can be linked to a conference series (a recurring event brand) via
            the admin endpoint <code>POST /api/v1/admin/matcher/link-past-conference-series</code>.
            Once linked, the SME past-attendance dimension works — if an SME's attended_sme_ids
            appears in the past record for the same series, they get +1.0 on the past-attendance
            dimension.
          </P>
        </Section>

        <Section id="topics" title="Topics">
          <P>
            Topics are a controlled vocabulary of themes that connect conferences and SMEs. The
            LLM pipeline discovers topics from conference abstracts and places them in a
            "pending review" queue. An admin approves or rejects them.
          </P>
          <H3>Topic lifecycle</H3>
          <Ol>
            <li>
              Scraper ingests a conference → LLM extraction suggests topic strings (e.g. "MLOps,"
              "vector databases," "RAG").
            </li>
            <li>
              The talk upload flow also suggests topic matches via fuzzy matching against the
              existing topic table.
            </li>
            <li>
              New strings land in the topic table with <code>pending_review=true</code>.
            </li>
            <li>
              An admin visits Settings → Topic review and approves or rejects each pending topic.
            </li>
            <li>
              Approved topics become part of the active vocabulary. They appear in conference and
              SME tag selectors and count in the topic-overlap dimension.
            </li>
          </Ol>
          <Callout kind="warning">
            Unapproved (pending) topics do NOT count in the matcher's topic-overlap Jaccard. Approve
            topics promptly after scraper runs for the SME dimension to be meaningful.
          </Callout>
        </Section>

        <Section id="settings" title="Settings & Tunables">
          <P>
            Settings → Tunables exposes every operational knob via the
            <code>GET/PATCH /api/v1/admin/settings</code> API. Changes take effect on the next
            matcher run without a restart (unless the change requires an embedding model swap).
          </P>
          <H3>Matcher gates</H3>
          <P>
            Three thresholds control what status a conference gets assigned. Lower a gate to let
            more conferences through to the next stage; raise it to enforce stricter relevance
            requirements.
          </P>
          <Dl>
            <dt>MATCH_M_GATE (default 0.55)</dt>
            <dd>Messaging fit gate — Stage A cutoff.</dd>
            <dt>MATCH_P_GATE (default 0.55)</dt>
            <dd>Pillar alignment gate — Stage B cutoff.</dd>
            <dt>MATCH_S_GATE (default 0.50)</dt>
            <dd>SME match gate — Stage C cutoff. Slightly lower because SME data is sparser.</dd>
          </Dl>
          <H3>Matcher stage weights</H3>
          <P>
            The pipeline normalizes these so they don't need to sum to 1.0. The ratio between them
            is what matters.
          </P>
          <Code>{`MATCH_W_MESSAGING = 0.40   # Stage A
MATCH_W_PILLAR   = 0.15   # Stage B
MATCH_W_SME      = 0.20   # Stage C
MATCH_W_JUDGE    = 0.45   # Stage D (LLM judge)`}</Code>
          <H3>SME ranker weights</H3>
          <P>
            Must sum to exactly 1.0 (the app validates this on startup). Adjust to prioritize
            topic-overlap over bio-similarity, or vice versa.
          </P>
          <Code>{`SME_W_TOPIC    = 0.30
SME_W_AUDIENCE = 0.25
SME_W_BIO      = 0.30
SME_W_LOCATION = 0.10
SME_W_PAST     = 0.05`}</Code>
          <H3>Feature flags</H3>
          <Dl>
            <dt>ENABLE_LLM_JUDGE</dt>
            <dd>Toggle Stage D. Disable to reduce per-rescore LLM cost (bulk rescores run all
              conferences).</dd>
            <dt>ENABLE_JUDGE_FEW_SHOT</dt>
            <dd>Include recent approve/reject decisions as examples in the judge prompt. Improves
              calibration but adds tokens per call.</dd>
            <dt>ENABLE_JUDGE_CACHE</dt>
            <dd>Reuse the cached judge score when the input hash matches. Almost always leave on.
            </dd>
            <dt>ENABLE_CFP_URGENCY_BOOST</dt>
            <dd>Toggle the +0.10 CFP-deadline boost.</dd>
            <dt>ENABLE_SERIES_MEMORY_BOOST</dt>
            <dd>Toggle the verdict-signed series-memory boost.</dd>
            <dt>ENABLE_FLAGSHIP_EVENT_BOOST</dt>
            <dd>Toggle the +0.15 flagship-event pattern boost.</dd>
            <dt>ENABLE_RECENCY_PENALTY</dt>
            <dd>Toggle the −0.05 far-future penalty.</dd>
          </Dl>
          <H3>Maintenance actions</H3>
          <P>
            Available directly on the Settings home page:
          </P>
          <Ul>
            <li>
              <strong>Rescore everything</strong> — enqueues one matcher run per non-quarantined
              conference. Async; check Diagnostics for progress. Use after: messaging document
              changes, pillar description edits, SME roster changes, or gate/weight adjustments.
            </li>
            <li>
              <strong>Backfill missing coordinates</strong> — resolves city → lat/lng for
              conferences without map coordinates. Rate-limited by Nominatim (1 req/sec).
            </li>
          </Ul>
        </Section>

        <Section id="workflows" title="Common Workflows">
          <H3>Onboarding a new conference</H3>
          <Ol>
            <li>It arrives automatically from the scraper OR you add it manually.</li>
            <li>
              If embedding chunks are missing (Stage A score = 0), check the scraper logs in
              Diagnostics.
            </li>
            <li>Run the matcher: conference page → "Run matcher" or admin API.</li>
            <li>Review the score breakdown, brief, and SME recommendations.</li>
            <li>Approve, archive, or queue for team review.</li>
          </Ol>
          <H3>Adding a new SME</H3>
          <Ol>
            <li>Create the SME on the SMEs page with full name, team, country.</li>
            <li>Write a detailed bio (paragraph or more — richer = better bio similarity).</li>
            <li>Add topic tags that match the SME's expertise.</li>
            <li>Link them to the relevant pillar from the pillar's SMEs tab.</li>
            <li>Run "Rescore everything" from Settings so the new SME appears in rankings.</li>
          </Ol>
          <H3>Adjusting matcher behavior</H3>
          <Ol>
            <li>
              <strong>Too many low-relevance conferences surfaced:</strong> raise
              <code>MATCH_M_GATE</code> or raise <code>MATCH_W_JUDGE</code> weight.
            </li>
            <li>
              <strong>High-quality conferences being filtered out:</strong> lower
              <code>MATCH_M_GATE</code> or check whether messaging documents are active and
              up to date.
            </li>
            <li>
              <strong>SME rankings don't feel right:</strong> adjust <code>SME_W_*</code> weights.
              Topic and bio are the strongest signals; location and past are secondary.
            </li>
            <li>
              <strong>Flagship events not surfacing:</strong> check <code>ENABLE_FLAGSHIP_EVENT_BOOST</code>
              is on and that the conference name matches a pattern in the flagship list.
            </li>
          </Ol>
          <H3>Bulk-importing reference data</H3>
          <Ol>
            <li>Settings → Workbook → "Download empty template" to get the XLSX structure.</li>
            <li>Fill in SMEs, topics, audiences, pillars, series on the respective sheets.</li>
            <li>"Upload &amp; preview" to see the diff (inserts / updates / deletes / errors).</li>
            <li>Fix any validation errors shown in the preview.</li>
            <li>"Apply" to commit. Automatically triggers a rescore.</li>
          </Ol>
        </Section>
      </article>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Content primitives
// ---------------------------------------------------------------------------

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

function Ul({ children }: { children: React.ReactNode }) {
  return <ul className="list-disc space-y-1.5 pl-5 text-sm text-fg-muted">{children}</ul>;
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
