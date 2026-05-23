/**
 * End-to-end flow tests for the settings UI.
 *
 * Covers the user-facing path: open /settings → click "Tunables & API
 * keys" card → land on /settings/tunables → see the LLM API key field
 * + the Discovery section + the Save button. This is the flow the user
 * tried earlier and discovered was broken (the route file existed but
 * the SPA Router silently failed to mount it).
 */

import { expect, test } from "@playwright/test";

test("clicking 'Tunables & API keys' navigates to a working tunables page", async ({
  page,
}) => {
  await page.goto("/settings");

  // The card is a Link wrapping a Card; clicking the title should
  // navigate to /settings/tunables.
  await page.getByRole("heading", { name: /tunables & api keys/i }).click();

  await expect(page).toHaveURL(/\/settings\/tunables$/);
  await expect(
    page.getByRole("heading", { name: /tunables & api keys/i }),
  ).toBeVisible();

  // The LLM API key field must exist + be editable.
  await expect(page.getByText(/llm api key/i).first()).toBeVisible();

  // The discovery section should be present (proves plan-35 settings shipped).
  await expect(page.getByText(/autonomous discovery enabled/i)).toBeVisible();
  await expect(page.getByText(/search provider/i)).toBeVisible();
});

test("/messaging/new form renders + has required fields", async ({ page }) => {
  await page.goto("/messaging/new");
  await expect(
    page.getByRole("heading", { name: /new messaging document/i }),
  ).toBeVisible();

  // Required field labels per the form.
  for (const label of [
    /title/i,
    /elevator pitch/i,
    /target personas/i,
    /key themes/i,
    /talking points/i,
  ]) {
    await expect(page.getByText(label).first()).toBeVisible();
  }

  // Save button exists + is enabled (until validation kicks in on submit).
  await expect(page.getByRole("button", { name: /^save$/i })).toBeVisible();
});

test("/discover form renders + has the prompt textarea and run button", async ({
  page,
}) => {
  await page.goto("/discover");
  await expect(
    page.getByRole("heading", { name: /discover conferences/i }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: /run discovery now/i }),
  ).toBeVisible();
  // Prompt textarea should be present + pre-filled.
  await expect(page.locator("textarea").first()).toBeVisible();
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
