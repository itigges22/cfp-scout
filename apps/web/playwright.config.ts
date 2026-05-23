/**
 * Playwright config for Scout's SPA smoke + e2e tests.
 *
 * Tests run against the live api container (default http://localhost:8000).
 * Override via $BASE_URL when pointing at a remote or CI environment.
 *
 * We deliberately keep the browser set to chromium-only for now —
 * cross-browser is a future concern; smoke coverage matters more.
 */
import { defineConfig, devices } from "@playwright/test";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:8000";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : 2,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: BASE_URL,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    actionTimeout: 10_000,
    navigationTimeout: 30_000,
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
