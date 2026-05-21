# apps/web — Scout Vite + React SPA

Production build (`pnpm build`) outputs to `dist/`, which is copied into the
api image's `static/` directory during the api Containerfile's spa-builder
stage. The SPA is then served by FastAPI at `/`.

Filled in step 08 of [`/PLANS/phase-1/`](../../PLANS/phase-1/).
