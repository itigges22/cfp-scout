/**
 * Visit every SPA route and assert the page actually renders.
 *
 * The bug that motivated this suite: `/settings/tunables` curled 200
 * because the SPA shell loaded, but the client-side router silently
 * failed to mount the child route. A pure HTTP smoke check missed it —
 * and still would, because `main.py`'s catch-all serves index.html with
 * a 200 for any path, including ones that don't exist.
 *
 * Two deliberate design choices, both learned from this suite rotting:
 *
 * 1. The route list is DERIVED from `src/routeTree.gen.ts`, not hardcoded.
 *    The old hardcoded list still contained `/discover` (deleted) while
 *    missing `/talks` and `/pillars/$id` (added). A generated list cannot
 *    drift: add a route file and it is covered on the next run.
 *
 * 2. Assertions are STRUCTURAL, not copy-based. The old list asserted
 *    `h1:has-text("Past conferences")` and `h1:has-text("Topics")`; both
 *    broke when the headings were reworded to "Past events" and "Topic
 *    vocabulary" — the pages were fine, the tests were wrong. We assert a
 *    level-1 heading exists inside <main>, which is what "the route
 *    mounted" actually means, and let copy change freely.
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

import { expect, test } from "@playwright/test";

const here = dirname(fileURLToPath(import.meta.url));

/**
 * Pull the static route paths out of the generated TanStack route tree.
 *
 * Excluded:
 *  - `$param` routes — they need a real id, so they live in
 *    conferences-flow.spec.ts where one is fetched from the API.
 *  - TanStack's `foo_/bar` non-nested-layout aliases, which resolve to
 *    the same URL as `foo/bar` and would just double every test.
 */
function staticRoutes(): string[] {
  const src = readFileSync(resolve(here, "../src/routeTree.gen.ts"), "utf8");
  const paths = new Set<string>();
  for (const m of src.matchAll(/^\s+'(\/[a-zA-Z0-9_/$.-]*)':/gm)) {
    const p = m[1];
    if (!p) continue;
    if (p.includes("$")) continue; // needs a real id
    if (/_\//.test(p)) continue; // non-nested-layout alias
    if (p === "/") continue; // index redirects; covered below explicitly
    paths.add(p);
  }
  return [...paths].sort();
}

const ROUTES = staticRoutes();

test("the generated route tree yields a plausible set of routes", () => {
  // Guards the parser itself: if routeTree.gen.ts changes shape and this
  // returns nothing, every other test in this file would vacuously pass.
  expect(ROUTES.length).toBeGreaterThan(8);
  expect(ROUTES).toContain("/dashboard");
  expect(ROUTES).toContain("/conferences");
});

for (const path of ROUTES) {
  test(`renders ${path}`, async ({ page }) => {
    const failures: string[] = [];
    page.on("pageerror", (e) => failures.push(`pageerror: ${e.message}`));
    page.on("response", (r) => {
      const url = r.url();
      // Only flag api 5xx — frontend chunk 404s during dev are noisy.
      if (url.includes("/api/") && r.status() >= 500) {
        failures.push(`${r.status()} ${url}`);
      }
    });

    await page.goto(path);

    // A mounted route puts a level-1 heading in the main region. The
    // layout shell's own headings live in <nav>/<aside>, so this cannot
    // pass on a blank page that merely loaded the SPA chrome.
    await expect(page.locator("main h1").first()).toBeVisible({
      timeout: 10_000,
    });

    if (failures.length > 0) {
      throw new Error(
        `Route ${path} mounted but errors fired:\n  - ${failures.join("\n  - ")}`,
      );
    }
  });
}

test("/ redirects into the app rather than rendering an empty shell", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.locator("main h1").first()).toBeVisible();
});

test("an unknown client-side path still serves the SPA, not a server error", async ({
  page,
}) => {
  const res = await page.goto("/definitely-not-a-route");
  expect(res?.status()).toBe(200);
});

test("an unknown /api path returns 404 JSON, never the SPA shell", async ({
  request,
}) => {
  // Regression guard for main.py's catch-all: API consumers must get
  // RFC 7807, not an HTML page with a 200.
  const res = await request.get("/api/v1/definitely-not-a-route");
  expect(res.status()).toBe(404);
  expect(res.headers()["content-type"] ?? "").toContain("json");
});
