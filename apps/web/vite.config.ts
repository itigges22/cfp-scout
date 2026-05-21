import path from "node:path";

import { TanStackRouterVite } from "@tanstack/router-plugin/vite";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Vite config — see https://vitejs.dev/config/
//
// Two notable things:
//   1. TanStackRouterVite generates `src/routeTree.gen.ts` from the file
//      structure under `src/routes/`. Don't edit that file by hand.
//   2. Tailwind v4 uses a Vite plugin, not PostCSS, so there's no
//      `postcss.config.js` or `tailwind.config.ts` for basic usage. Design
//      tokens live in `src/styles/index.css` under `@theme`.
export default defineConfig({
  plugins: [
    TanStackRouterVite({
      target: "react",
      autoCodeSplitting: true,
    }),
    react(),
    tailwindcss(),
  ],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    // Dev server runs on host; api is in the container at :8000.
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: false,
      },
    },
  },
  build: {
    // Output is consumed by the api Containerfile's spa-builder stage and
    // copied into /app/static/ in the runtime image.
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: true,
  },
});
