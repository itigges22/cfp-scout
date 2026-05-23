/**
 * Visit every SPA route and assert the page actually renders content.
 *
 * The bug that motivated this suite: `/settings/tunables` curled 200
 * because the SPA shell loaded, but the client-side router silently
 * failed to mount the child route. A pure HTTP smoke check missed it.
 * Here we navigate via the Router and assert a route-specific selector
 * is visible — anything client-side broken surfaces as a real failure.
 */

import { expect, test } from "@playwright/test";

/**
 * One entry per top-level SPA route. ``selector`` must match a unique
 * heading or label that only renders when the route's React component
 * mounts — never the layout shell, the sidebar, or a static header.
 */
const ROUTES = [
  { path: "/dashboard", selector: 'h1:has-text("Dashboard")' },
  { path: "/conferences", selector: 'h1:has-text("Conferences")' },
  { path: "/discover", selector: 'h1:has-text("Discover conferences")' },
  { path: "/graph", selector: "canvas, .react-force-graph-2d, h1:has-text('Graph')" },
  { path: "/smes", selector: 'h1:has-text("SMEs"), h1:has-text("Subject")' },
  { path: "/audiences", selector: 'h1:has-text("Audiences")' },
  { path: "/messaging", selector: 'h1:has-text("Messaging")' },
  { path: "/messaging/new", selector: 'h1:has-text("New messaging document")' },
  { path: "/past-conferences", selector: 'h1:has-text("Past conferences")' },
  { path: "/topics", selector: 'h1:has-text("Topics")' },
  { path: "/agent", selector: 'form, textarea, h1:has-text("Agent")' },
  { path: "/diagnostics", selector: 'h1:has-text("Diagnostics")' },
  { path: "/settings", selector: 'h1:has-text("Settings")' },
  { path: "/settings/tunables", selector: 'h1:has-text("Tunables")' },
];

for (const { path, selector } of ROUTES) {
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
    await expect(page.locator(selector).first()).toBeVisible({ timeout: 10_000 });

    if (failures.length > 0) {
      throw new Error(
        `Route ${path} mounted but errors fired:\n  - ${failures.join("\n  - ")}`,
      );
    }
  });
}

test("conference detail + brief render", async ({ page, request }) => {
  // Pick a real conference id from the live API.
  const listRes = await request.get("/api/v1/conferences?per_page=1");
  expect(listRes.ok()).toBeTruthy();
  const body = await listRes.json();
  const cid = body.items?.[0]?.id;
  test.skip(!cid, "no conferences in DB to test the detail route");

  await page.goto(`/conferences/${cid}`);
  await expect(page.getByRole("heading").first()).toBeVisible();

  await page.goto(`/conferences/${cid}/brief`);
  await expect(page.getByRole("heading").first()).toBeVisible();
});
