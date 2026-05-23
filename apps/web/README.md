# apps/web — Scout Vite + React SPA

Vite 6 + React 19 + TanStack Router + TanStack Query + Tailwind v4. Built
into the api image at deploy time and served by FastAPI from the same
origin at `/`, so there is no separate frontend service in production.

## Routes

File-based via TanStack Router. Naming convention:

- `foo.tsx` — parent route. Must render `<Outlet />` for children to show.
- `foo.$id.tsx` — child of `foo` (renders inside the parent's `<Outlet />`).
- `foo_.$id.tsx` — flat/sibling route (trailing underscore on the segment).
  Same URL as `foo/$id` but does **not** nest under `foo.tsx`.

Scout uses the flat convention extensively because the list pages have no
`<Outlet />`: see `conferences_.$id.tsx`, `conferences_.$id.brief.tsx`,
`messaging_.$id.tsx`, `messaging_.new.tsx`, `settings_.tunables.tsx`.

## Layout

```
src/
  routes/         File-based TanStack Router routes
  components/     Reusable components; per-feature subdirs (dashboard/,
                  sme/, messaging/, conferences/, past-conferences/,
                  team/, layout/, ui/)
  lib/
    api.ts        Typed client over fetch
    api-types.ts  Handwritten TS types matching the api
    query-client.ts, utils.ts
public/           Static assets served as-is (e.g. world-110m.json)
```

## Daily edit loop

```bash
make spa          # rebuilds the SPA in a throwaway UBI node-22 container
                  # and drops the output into apps/api/static/
```

Hard-reload the browser to drop the old bundle hash. The api serves
whatever is in `static/`, so there's no separate dev server to manage.

## Notes

- `src/components/dashboard/WorldMap.tsx` uses `react-simple-maps` with a
  self-hosted TopoJSON at `public/world-110m.json`. react-simple-maps v3
  swallows fetch errors silently when CDNs misbehave, so we bundle the
  map data ourselves.
