/**
 * End-to-end flow tests for the settings UI.
 *
 * Covers the user-facing path: open /settings → click the "Tunables & API
 * keys" card → land on /settings/tunables → see the LLM API key field and
 * the Discovery section. This is the flow that was once broken by the
 * router silently failing to mount the child route.
 *
 * Note on selectors: the tunables card is a <Link> wrapping the title
 * text, NOT a heading. An earlier version of this test looked for a
 * heading and had been failing ever since the card was restyled.
 */

import { expect, test } from "@playwright/test";

test("clicking 'Tunables & API keys' navigates to a working tunables page", async ({
  page,
}) => {
  await page.goto("/settings");

  await page.getByRole("link", { name: /tunables & api keys/i }).click();

  await expect(page).toHaveURL(/\/settings\/tunables$/);
  // The destination renders its own h1 — proof the child route mounted
  // rather than the shell just changing the URL.
  await expect(page.locator("main h1")).toBeVisible();

  // The LLM API key field must exist.
  await expect(page.getByText(/llm api key/i).first()).toBeVisible();

  // The discovery settings must be present.
  await expect(page.getByText(/discovery/i).first()).toBeVisible();
});

test("every settings card navigates somewhere that mounts", async ({ page }) => {
  // The settings page is a hub of links; a dead one is invisible until a
  // user clicks it. Walk them all rather than spot-checking one.
  await page.goto("/settings");
  // Wait for the hub to paint. `goto` resolves on document load, but this is
  // a client-rendered SPA, so counting links immediately raced React and the
  // test failed intermittently with "expected > 2" on a page that has five.
  await expect(page.locator("main a").first()).toBeVisible();
  const names = await page
    .locator("main a")
    .evaluateAll((els) =>
      els
        .map((e) => (e as HTMLAnchorElement).getAttribute("href"))
        .filter((h): h is string => !!h && h.startsWith("/")),
    );
  expect(names.length).toBeGreaterThan(2);

  for (const href of [...new Set(names)]) {
    await page.goto(href);
    await expect(
      page.locator("main h1").first(),
      `settings linked to ${href}, which did not mount`,
    ).toBeVisible({ timeout: 10_000 });
  }
});

test("/messaging/new form renders + has required fields", async ({ page }) => {
  await page.goto("/messaging/new");
  await expect(page.locator("main h1")).toBeVisible();

  for (const label of [
    /title/i,
    /elevator pitch/i,
    /target personas/i,
    /key themes/i,
    /talking points/i,
  ]) {
    await expect(page.getByText(label).first()).toBeVisible();
  }

  await expect(page.getByRole("button", { name: /^save$/i })).toBeVisible();
});

test("'+ New conference' button on /conferences opens the dialog", async ({
  page,
}) => {
  await page.goto("/conferences");
  await page.getByRole("button", { name: /\+ new conference/i }).click();
  await expect(
    page.getByRole("heading", { name: /add a conference manually/i }),
  ).toBeVisible();
});
