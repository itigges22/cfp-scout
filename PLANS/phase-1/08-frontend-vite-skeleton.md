# 08 — Frontend Vite + React Skeleton (served by FastAPI)

## Goal
A Vite-built React SPA bundled into the api container. No separate web
container, no Next.js, no SSR. Single origin = no CORS in production.

## Prereqs
- 06 (API up; serves SPA via StaticFiles)

## Stack inside `/apps/web`
- Vite 5
- React 19
- TypeScript strict
- Tailwind CSS + design tokens
- shadcn/ui primitives (copied into repo, not packaged)
- TanStack Query for server state
- TanStack Router (typed, file-based routing)
- `openapi-typescript` + `openapi-fetch` for the typed API client
- Vitest + Playwright for tests

## Tasks
- [ ] Scaffold with `pnpm create vite@latest apps/web --template react-ts`.
- [ ] TS config strict: `noImplicitAny`, `strictNullChecks`, `noUncheckedIndexedAccess`,
      `noImplicitReturns`. Treat warnings as errors in CI.
- [ ] Tailwind v4 with design tokens in `tailwind.config.ts`:
  - palette aligned with Red Hat (red accent, near-black canvas, off-white text)
  - typography + spacing scale
  - dark mode via `class` strategy; dark default
- [ ] Add shadcn/ui primitives:
      Button, Input, Textarea, Select, Dialog, Sheet, Table, Card, Badge,
      Toast, Tabs, DropdownMenu, Form, ScrollArea, Tooltip, Popover,
      Command (cmd-k palette), Stepper (wizard component).
- [ ] **TanStack Router**:
  - file-based routes under `src/routes/`
  - typed `Route` definitions; type-safe links
- [ ] API client codegen:
  - `pnpm gen:api` reads `apps/api/openapi.json` (committed) or fetches from a running api
  - writes `src/api/types.ts` and `src/api/client.ts`
  - `apiClient` is a typed `openapi-fetch` instance with shared error handling
- [ ] Layout:
  - left rail nav: Dashboard, Conferences, SMEs, Audiences, Messaging, Agent, Graph, Diagnostics, Settings
  - top bar: env badge, current-month LLM spend (small badge), notification bell, settings cog
  - main pane with breadcrumbs
- [ ] Route shells (real content lands later):
  - `/` → redirects to `/dashboard`
  - `/dashboard` (step 20)
  - `/conferences` and `/conferences/[id]` (step 20)
  - `/smes` (step 09)
  - `/audiences` (step 09)
  - `/messaging` (step 09)
  - `/agent` (step 22)
  - `/graph` (step 21)
  - `/diagnostics` (step 26)
  - `/settings`
- [ ] Loading + error boundaries per route.
- [ ] **Build artifact**: `pnpm build` outputs `apps/web/dist/`. The
      api Containerfile's stage-1 copies `dist/` into `apps/api/static/`.
      For dev, run `pnpm dev` on host (port 5173); CORS allowed only in `ENV=dev`.
- [ ] Vitest set up with one smoke test.
- [ ] Playwright set up with one smoke test hitting the dashboard route.

## Security notes
- CSP set via FastAPI middleware (step 06) since the api serves the SPA.
  No `unsafe-inline` in production.
- `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`.
- HSTS in production.
- The API client never reads `LLM_API_KEY`. Frontend talks only to FastAPI.
- File uploads (PDF, CSV) validated client-side as UX; server is source of truth.
- All user-typed text rendered with React's default escaping; no `dangerouslySetInnerHTML`
  outside the chat markdown renderer (which uses a strict sanitizer — step 22).

## Acceptance criteria
- [ ] `make up` → `http://localhost:8000/` loads the SPA.
- [ ] All route shells render with empty states.
- [ ] `pnpm gen:api` produces TS types and the client compiles strict.
- [ ] `pnpm lint && pnpm test && pnpm build` all pass in container build.
- [ ] No console errors on a fresh page load.
- [ ] Dark mode is the default; toggle persists in localStorage.

## Open questions for the user
- **Design system** — shadcn (recommended) vs PatternFly. shadcn is the modern
  internal-tool default; PatternFly is heavier and more dated.
- **Dark default** — recommend dark for the Red Hat console feel. Confirm.

## Risks
- A frontend change requires rebuilding the api image. `make build-spa` is fast;
  dev mode uses Vite hot-reload to avoid the round-trip.
- shadcn components live in our repo. We own them. Worth it for customization.
