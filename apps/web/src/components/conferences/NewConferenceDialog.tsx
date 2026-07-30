/**
 * NewConferenceDialog — modal form for adding a conference manually.
 *
 * POST /api/v1/conferences returns as soon as the row + embedding exist
 * (~1s). It used to run the matcher inline too — 16 seconds on a frozen
 * dialog against a live LLM. Scoring now happens on the detail page this
 * navigates to, behind its ScorePanel skeleton.
 */

import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { ApiError, conferencesApi, fetchEventKinds } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

type Props = {
  onClose: () => void;
  onCreated: (conferenceId: string) => void;
};

export function NewConferenceDialog({ onClose, onCreated }: Props) {
  const [name, setName] = useState("");
  // This form never sent event_kind. It does not 422 — the field defaults
  // to "corporate" server-side — which is the actual problem: every
  // hand-added event silently became corporate, including grassroots and
  // hackathons. That is not cosmetic, because the finder list defaults to
  // exclude_grassroot=true, so a mislabelled grassroot event stays visible
  // when it should not, and a real one cannot be filtered out.
  //
  // The vocabulary is operator-owned (the `event_kinds` setting) — read it,
  // never hardcode it, or this form disagrees with what the extractor and
  // the filters use.
  const [eventKind, setEventKind] = useState("");
  const kinds = useQuery({
    queryKey: ["event-kinds"],
    queryFn: fetchEventKinds,
    staleTime: 5 * 60_000,
  });
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [locationCity, setLocationCity] = useState("");
  const [locationCountry, setLocationCountry] = useState("");
  const [isVirtual, setIsVirtual] = useState(false);
  const [venue, setVenue] = useState("");
  const [website, setWebsite] = useState("");
  const [cfpCloseAt, setCfpCloseAt] = useState("");
  const [cfpOpenAt, setCfpOpenAt] = useState("");
  const [topicsStr, setTopicsStr] = useState("");
  const [cfpTopicsStr, setCfpTopicsStr] = useState("");
  const [acceptanceRate, setAcceptanceRate] = useState<string>("");
  const [estimatedCost, setEstimatedCost] = useState<string>("");
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      conferencesApi.create({
        name: name.trim(),
        event_kind: eventKind,
        start_date: startDate || null,
        end_date: endDate || null,
        location_city: locationCity.trim() || null,
        location_country: locationCountry.trim().toUpperCase() || null,
        is_virtual: isVirtual,
        venue: venue.trim() || null,
        website: website.trim() || null,
        cfp_open_at: cfpOpenAt || null,
        cfp_close_at: cfpCloseAt || null,
        cfp_topics_of_interest: splitCsv(cfpTopicsStr),
        topics: splitCsv(topicsStr),
        acceptance_rate_percent: acceptanceRate
          ? Number.parseInt(acceptanceRate, 10)
          : null,
        estimated_cost_usd: estimatedCost
          ? Number.parseInt(estimatedCost, 10)
          : null,
        actor_label: "manual_entry",
      }),
    onSuccess: (data) => {
      onCreated(data.conference.id);
    },
    onError: (err) => {
      if (err instanceof ApiError) {
        setError(err.problem.detail || err.problem.title || err.message);
      } else {
        setError(String((err as Error).message));
      }
    },
  });

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!name.trim()) {
      setError("Conference name is required.");
      return;
    }
    if (locationCountry && locationCountry.trim().length !== 2) {
      setError("Country must be a 2-letter ISO code (e.g. US, GB).");
      return;
    }
    if (endDate && startDate && endDate < startDate) {
      setError("End date must be after start date.");
      return;
    }
    mutation.mutate();
  };

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Add a conference manually</DialogTitle>
          <DialogDescription>
            For events Scout hasn&rsquo;t discovered. Saves in about a second;
            the detail page opens and scores it while you watch.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={submit} className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <Field label="Name" required full>
            <Input
              value={name}
              onChange={(e) => setName(e.currentTarget.value)}
              maxLength={200}
              placeholder="KubeCon EU 2027"
              autoFocus
            />
          </Field>

          <Field label="Type" required full>
            <select
              value={eventKind}
              onChange={(e) => setEventKind(e.currentTarget.value)}
              className="h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm"
            >
              <option value="" disabled>
                {kinds.isLoading ? "Loading…" : "Select a type"}
              </option>
              {(kinds.data ?? []).map((k) => (
                <option key={k} value={k}>
                  {k.replace(/_/g, " ")}
                </option>
              ))}
            </select>
          </Field>

          <Field label="Start date">
            <Input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.currentTarget.value)}
            />
          </Field>
          <Field label="End date">
            <Input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.currentTarget.value)}
            />
          </Field>

          <Field label="City">
            <Input
              value={locationCity}
              onChange={(e) => setLocationCity(e.currentTarget.value)}
              maxLength={120}
              placeholder="Boston"
            />
          </Field>
          <Field label="Country (ISO-2)">
            <Input
              value={locationCountry}
              onChange={(e) =>
                setLocationCountry(e.currentTarget.value.slice(0, 2))
              }
              maxLength={2}
              placeholder="US"
            />
          </Field>

          <Field label="Venue">
            <Input
              value={venue}
              onChange={(e) => setVenue(e.currentTarget.value)}
              maxLength={200}
              placeholder="Hynes Convention Center"
            />
          </Field>
          <Field label="Website">
            <Input
              type="url"
              value={website}
              onChange={(e) => setWebsite(e.currentTarget.value)}
              placeholder="https://…"
            />
          </Field>

          <Field label="CFP opens">
            <Input
              type="date"
              value={cfpOpenAt}
              onChange={(e) => setCfpOpenAt(e.currentTarget.value)}
            />
          </Field>
          <Field label="CFP closes">
            <Input
              type="date"
              value={cfpCloseAt}
              onChange={(e) => setCfpCloseAt(e.currentTarget.value)}
            />
          </Field>

          <Field label="Acceptance rate %">
            <Input
              type="number"
              min={0}
              max={100}
              value={acceptanceRate}
              onChange={(e) => setAcceptanceRate(e.currentTarget.value)}
              placeholder="25"
            />
          </Field>
          <Field label="Estimated cost (USD)">
            <Input
              type="number"
              min={0}
              max={100000}
              value={estimatedCost}
              onChange={(e) => setEstimatedCost(e.currentTarget.value)}
              placeholder="1200"
            />
          </Field>

          <Field
            label="Topics"
            full
            hint="Comma-separated. Matcher uses these to find candidate SMEs."
          >
            <Input
              value={topicsStr}
              onChange={(e) => setTopicsStr(e.currentTarget.value)}
              placeholder="llm, rag, inference"
            />
          </Field>
          <Field
            label="CFP topics of interest"
            full
            hint="Comma-separated. What the program committee wants submissions on."
          >
            <Input
              value={cfpTopicsStr}
              onChange={(e) => setCfpTopicsStr(e.currentTarget.value)}
              placeholder="LLM evaluation, retrieval, agents"
            />
          </Field>

          <div className="col-span-full flex items-center gap-2">
            <input
              id="is-virtual"
              type="checkbox"
              checked={isVirtual}
              onChange={(e) => setIsVirtual(e.currentTarget.checked)}
              className="h-4 w-4 rounded border-border bg-surface accent-accent"
            />
            <Label htmlFor="is-virtual" className="cursor-pointer">
              Virtual event
            </Label>
          </div>

          {error && (
            <div className="col-span-full rounded border border-danger/40 bg-danger/10 p-3 text-sm text-danger">
              {error}
            </div>
          )}

          <DialogFooter className="col-span-full">
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button
              type="submit"
              // Name is required; a type must be chosen rather than
              // defaulted, so the operator states it instead of silently
              // getting "corporate".
              disabled={mutation.isPending || !name.trim() || !eventKind}
            >
              {mutation.isPending ? "Saving + scoring…" : "Save & run matcher"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function Field({
  label,
  required,
  hint,
  full,
  children,
}: {
  label: string;
  required?: boolean;
  hint?: string;
  full?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className={`flex flex-col gap-1.5 ${full ? "col-span-full" : ""}`}>
      <Label className="text-sm">
        {label}
        {required ? <span className="ml-0.5 text-danger">*</span> : null}
      </Label>
      {children}
      {hint ? <p className="text-xs text-fg-muted">{hint}</p> : null}
    </div>
  );
}

function splitCsv(s: string): string[] {
  return s
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);
}
