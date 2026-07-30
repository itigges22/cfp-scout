// @ts-check
//
// Flat-config ESLint setup. Standard React + TS, react-hooks rules,
// react-refresh check for dev-only.
//
// `globals` package supplies the browser + ES2022 + Node names so
// `no-undef` doesn't flag `document`, `window`, `setTimeout`, etc.
// React 19's automatic JSX runtime means we don't `import React`, but
// some files use `React.ComponentProps<...>` for typing — we register
// it as a readonly global so eslint stops complaining without forcing
// an explicit import everywhere.

import js from "@eslint/js";
import tseslint from "@typescript-eslint/eslint-plugin";
import tsparser from "@typescript-eslint/parser";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import globals from "globals";

export default [
  {
    ignores: [
      "dist",
      "node_modules",
      "src/routeTree.gen.ts",
      // TS project-reference build artifacts for vite.config.ts. Source
      // is vite.config.ts; the .d.ts/.js are emit-only and shouldn't be
      // linted.
      // Test-runner config, not app source. It intentionally uses vitest's
      // own defineConfig, which the app tsconfig does not (and should not)
      // typecheck against.
      "vitest.config.ts",
      "vite.config.d.ts",
      "vite.config.js",
      "*.tsbuildinfo",
    ],
  },
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      parser: tsparser,
      ecmaVersion: 2022,
      sourceType: "module",
      parserOptions: {
        project: "./tsconfig.json",
        tsconfigRootDir: import.meta.dirname,
      },
      globals: {
        ...globals.browser,
        ...globals.es2022,
        // React 19's automatic JSX transform; we don't `import React` but
        // some files reference React.* type-only.
        React: "readonly",
      },
    },
    plugins: {
      "@typescript-eslint": tseslint,
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...js.configs.recommended.rules,
      ...tseslint.configs.recommended.rules,
      ...reactHooks.configs.recommended.rules,
      "react-refresh/only-export-components": [
        "warn",
        { allowConstantExport: true },
      ],
      "@typescript-eslint/no-unused-vars": [
        "warn",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
      // react-force-graph-2d (plan 21) hands us untyped event payloads;
      // we cast at the boundary with `as GraphNode`. Pinning `any` to
      // a warning so it's visible but doesn't fail CI — proper typings
      // would mean shipping declaration overlays for a 3rd-party lib.
      "@typescript-eslint/no-explicit-any": "warn",
    },
  },
  // The vite config is Node-side, not browser.
  {
    files: ["vite.config.ts", "*.config.{ts,js}"],
    languageOptions: {
      globals: {
        ...globals.node,
      },
    },
  },
];
