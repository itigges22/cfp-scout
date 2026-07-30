/**
 * Unit tests for the SPA's pure logic.
 *
 * Separate from vite.config.ts on purpose: vite 5's `defineConfig` rejects a
 * `test` block, and importing vitest's `defineConfig` there drags vite 6's
 * types in beside the project's vite 5 — which breaks `tsc -b`, and with it
 * the container image build.
 *
 * Node environment, not jsdom: the browser-level questions — does the page
 * mount, does the button open the dialog, does the route resolve — are
 * answered by e2e/ with Playwright against a real server, which is a
 * stronger check than a simulated DOM.
 */
import path from "node:path";

import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
