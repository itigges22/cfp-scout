/**
 * Guard the SPA↔API contract.
 *
 * `src/lib/api-types.ts` is 1000+ lines of HAND-MAINTAINED types whose own
 * header says `pnpm gen:api` will replace it — except `gen:api` points at
 * `../api/openapi.json`, which does not exist, so it has never been
 * runnable. Nothing checks that the ~60 endpoints `src/lib/api.ts` calls
 * still exist on the server.
 *
 * That is how six pillar endpoints kept being called by the client long
 * after a migration dropped the tables underneath them: rename a route or
 * delete a handler and TypeScript still compiles, because it is typing a
 * `fetch` cast, not a real contract.
 *
 * These tests fetch the live OpenAPI schema and assert every path the
 * client calls actually resolves.
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

import { expect, test } from "@playwright/test";

const here = dirname(fileURLToPath(import.meta.url));

/** Collapse `${id}` / `{conference_id}` so client and server forms compare. */
function normalise(path: string): string {
  return path.replace(/\$\{[^}]+\}/g, "{}").replace(/\{[^}]+\}/g, "{}");
}

/** Every `${BASE}/...` template literal in the client. */
function clientPaths(): string[] {
  const src = readFileSync(resolve(here, "../src/lib/api.ts"), "utf8");
  const found = new Set<string>();
  for (const m of src.matchAll(/`\$\{BASE\}(\/[^`?]*)/g)) {
    let p = normalise((m[1] ?? "").trim());
    // Anything still holding a `$` is an interpolation we could not
    // resolve — a nested template building a query string, e.g.
    // `${BASE}/talks${qs ? `?${qs}` : ""}`. The path ends there.
    p = p.split("$")[0] ?? "";
    // A path parameter always follows a slash (`/conferences/{}`). A `{}`
    // glued to the end of a segment is an interpolated query string,
    // not part of the path.
    p = p.replace(/([^/])\{\}$/, "$1");
    p = p.replace(/\/$/, "");
    if (p) found.add(p);
  }
  return [...found].sort();
}

test("the client-path parser finds a plausible number of endpoints", () => {
  // Without this, a parser regression makes the contract test below pass
  // by checking nothing at all.
  const paths = clientPaths();
  expect(paths.length).toBeGreaterThan(30);
  expect(paths).toContain("/conferences");
});

test("every endpoint src/lib/api.ts calls exists in the OpenAPI schema", async ({
  request,
}) => {
  const res = await request.get("/api/openapi.json");
  expect(res.ok()).toBeTruthy();
  const schema = await res.json();

  const serverPaths = new Set(
    Object.keys(schema.paths ?? {}).map((p) =>
      normalise(p.replace(/^\/api\/v1/, "")),
    ),
  );

  const missing = clientPaths().filter((p) => !serverPaths.has(p));

  expect(
    missing,
    `The SPA calls endpoints the API does not serve:\n  ${missing.join("\n  ")}`,
  ).toEqual([]);
});

test("the SPA does not keep its own copy of the event-kind vocabulary", () => {
  // This used to assert that a hardcoded EVENT_KINDS array in api-types.ts
  // matched the server. Two hand-synced copies of one enum, and they had
  // already drifted once (`team_managed` was removed server-side and the
  // client kept offering it).
  //
  // There is no copy now: the kinds are an operator SETTING, and the SPA
  // reads them at runtime via fetchEventKinds(). So the property worth
  // guarding flipped — a literal list reappearing is the regression.
  const src = readFileSync(resolve(here, "../src/lib/api-types.ts"), "utf8");
  expect(
    src.match(/export const EVENT_KINDS\s*=/),
    "a hardcoded EVENT_KINDS list is back in api-types.ts — the vocabulary " +
      "is operator-owned and must be read from settings, not restated here",
  ).toBeNull();

  const client = readFileSync(resolve(here, "../src/lib/api.ts"), "utf8");
  expect(
    client.includes("fetchEventKinds"),
    "the SPA no longer has a way to read the operator's event kinds",
  ).toBeTruthy();
});

test("every event kind the operator has configured is actually insertable", async ({
  request,
}) => {
  // POST /conferences runs the matcher INLINE, and against a live LLM that
  // is ~16s per conference — so this walks minutes, not seconds, when the
  // stack is pointed at a real endpoint rather than dry-run.
  test.setTimeout(5 * 60_000);
  // The property the old test was really after: whatever vocabulary the SPA
  // offers, the API must accept. Now read from the same place the SPA reads
  // it, so this cannot drift by construction.
  const settings = await request.get("/api/v1/admin/settings");
  expect(settings.ok()).toBeTruthy();
  const items = (await settings.json())?.items ?? [];
  const row = items.find((i: { spec?: { name?: string } }) => i.spec?.name === "event_kinds");
  const kinds: string[] = Array.isArray(row?.value) ? row.value : [];
  expect(kinds.length, "no event_kinds setting on the server").toBeGreaterThan(0);

  // Unique per run: the name becomes a slug, and a probe left behind by an
  // earlier failed run makes every later run 409 on the duplicate — which
  // reads as "the API rejected this event kind" when it did nothing of the
  // sort. The cleanup below is best-effort, so the name must not collide.
  // Date.now alone is enough to be unique per run and avoids a Node
  // global that the browser-targeted eslint config does not know about.
  const stamp = String(Date.now());
  for (const kind of kinds) {
    const created = await request.post("/api/v1/conferences", {
      data: { name: `Contract probe ${kind} ${stamp}`, event_kind: kind },
      // Overrides the 10s actionTimeout in playwright.config.ts for this
      // call only. Raising it globally would hide genuine hangs everywhere
      // else; this one endpoint is legitimately slow because it scores the
      // conference inline before responding.
      timeout: 90_000,
    });
    expect(
      created.status(),
      `POST /conferences rejected event_kind="${kind}" which the settings ` +
        `page offers (body: ${await created.text()})`,
    ).toBe(201);
    // MUST clean up. This runs against whatever stack BASE_URL points at —
    // including a real local one — and a probe left behind shows up in the
    // operator's conference list as junk. An earlier version left seven.
    const id = (await created.json())?.conference?.id;
    if (id) {
      const gone = await request.delete(`/api/v1/conferences/${id}`, {
        timeout: 30_000,
      });
      expect(
        gone.status(),
        `probe conference ${id} could not be deleted and is now polluting the ` +
          `database this test ran against`,
      ).toBeLessThan(300);
    }
  }
});
