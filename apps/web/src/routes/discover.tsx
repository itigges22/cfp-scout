/**
 * /discover — autonomous conference discovery (plan 35, PRD §1 + §4).
 *
 * Editable template prompt. Hit "Run now" to trigger a synchronous
 * discovery run: search via the configured provider → Crawl4AI fetch →
 * existing extraction pipeline → conferences land in /conferences.
 *
 * Defaults read from settings.discovery_template_prompt and
 * discovery_max_results_per_run. Changing them in /settings/tunables
 * also updates the next cron-fired run (06:00 UTC daily by default).
 */

import { useMutation } from "@tanstack/react-query";
import { Link, createFileRoute } from "@tanstack/react-router";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, discoveryApi } from "@/lib/api";
import type { DiscoveryResult } from "@/lib/api";
import { PageHeader } from "@/routes/dashboard";

export const Route = createFileRoute("/discover")({
  component: DiscoverPage,
});

const DEFAULT_PROMPT =
  "Upcoming AI conferences with open call for papers (CFP) closing in " +
  "the next six months. Focus on large language models, RAG, agentic " +
  "AI, MLOps, model serving, AI safety, inference performance, GPU " +
  "infrastructure, AI evaluations, and AI for enterprise software.";

function DiscoverPage() {
  const [prompt, setPrompt] = useState(DEFAULT_PROMPT);
  const [maxResults, setMaxResults] = useState<string>("20");
  const [error, setError] = useState<string | null>(null);
  const [lastResult, setLastResult] = useState<DiscoveryResult | null>(null);

  const mut = useMutation({
    mutationFn: () =>
      discoveryApi.runNow({
        prompt: prompt.trim() || undefined,
        max_results: maxResults ? Number.parseInt(maxResults, 10) : undefined,
      }),
    onSuccess: (data) => {
      setError(null);
      setLastResult(data);
    },
    onError: (err) => {
      if (err instanceof ApiError) {
        setError(err.problem.detail || err.problem.title);
      } else {
        setError(String((err as Error).message));
      }
    },
  });

  const inFlight = mut.isPending;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Discover conferences"
        description="Search the web with a prompt; Scout crawls each hit and runs it through the extraction pipeline. Discovered conferences land in /conferences with their matcher scores."
      />

      <Card>
        <CardHeader>
          <CardTitle>Search prompt</CardTitle>
          <CardDescription>
            Edit before running to tune what kinds of conferences Scout
            finds. The default is sourced from{" "}
            <Link
              to="/settings/tunables"
              className="text-accent hover:underline"
            >
              settings.discovery_template_prompt
            </Link>{" "}
            and also runs on the daily 06:00 UTC cron.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.currentTarget.value)}
            rows={5}
            className="min-h-[7rem] rounded-md border border-border bg-surface px-3 py-2 text-sm"
            placeholder={DEFAULT_PROMPT}
          />
          <div className="flex flex-wrap items-end gap-3">
            <div className="flex flex-col gap-1">
              <Label className="text-sm">Max results</Label>
              <Input
                type="number"
                min={1}
                max={100}
                value={maxResults}
                onChange={(e) => setMaxResults(e.currentTarget.value)}
                className="w-32"
              />
            </div>
            <Button onClick={() => mut.mutate()} disabled={inFlight}>
              {inFlight ? "Running…" : "Run discovery now"}
            </Button>
            {inFlight && (
              <span className="text-xs text-fg-muted">
                Search + crawl + per-page LLM extraction can take 1–3 minutes.
              </span>
            )}
          </div>
          {error && (
            <div className="rounded border border-danger/40 bg-danger/10 p-3 text-sm text-danger">
              {error}
            </div>
          )}
        </CardContent>
      </Card>

      {lastResult && <ResultPanel result={lastResult} />}
    </div>
  );
}

function ResultPanel({ result }: { result: DiscoveryResult }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Last run</CardTitle>
        <CardDescription>
          Provider <strong>{result.provider}</strong> · returned{" "}
          {result.search_hits} search hit{result.search_hits === 1 ? "" : "s"} ·
          crawled {result.crawled} · <strong>{result.new_conferences}</strong>{" "}
          new conferences · {result.updated_conferences} merged ·{" "}
          {result.parse_failures} parse failures
        </CardDescription>
      </CardHeader>
      <CardContent>
        {result.search_error && (
          <div className="mb-3 rounded border border-danger/40 bg-danger/10 p-3 text-sm text-danger">
            Search step error: {result.search_error}
          </div>
        )}
        {result.outcomes.length === 0 ? (
          <p className="text-sm text-fg-muted">No URLs returned.</p>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-xs uppercase tracking-wider text-fg-muted">
              <tr className="border-b border-border-subtle">
                <th className="py-1 text-left">URL</th>
                <th className="py-1 text-left">Title</th>
                <th className="py-1 text-left">Parse status</th>
                <th className="py-1 text-left">Conference</th>
              </tr>
            </thead>
            <tbody>
              {result.outcomes.map((o) => (
                <tr
                  key={o.url}
                  className="border-b border-border-subtle/60 align-top"
                >
                  <td className="py-1.5">
                    <a
                      href={o.url}
                      target="_blank"
                      rel="noreferrer noopener"
                      className="text-accent hover:underline"
                    >
                      {o.url.length > 60
                        ? o.url.slice(0, 60) + "…"
                        : o.url}
                    </a>
                  </td>
                  <td className="py-1.5 text-fg-muted">{o.title || "—"}</td>
                  <td className="py-1.5 font-mono text-xs">
                    {o.parse_status || (o.error ? "error" : "—")}
                  </td>
                  <td className="py-1.5">
                    {o.conference_id ? (
                      <Link
                        to="/conferences/$id"
                        params={{ id: o.conference_id }}
                        className="text-accent hover:underline"
                      >
                        open
                      </Link>
                    ) : (
                      <span className="text-fg-muted">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="mt-3 text-xs text-fg-muted">
          Started {result.started_at} · finished {result.finished_at}
        </p>
      </CardContent>
    </Card>
  );
}
