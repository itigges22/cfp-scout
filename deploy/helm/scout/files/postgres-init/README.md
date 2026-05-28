# Postgres init scripts

The chart's `postgres-init-configmap.yaml` loads these SQL files via
`.Files.Get` and mounts them into the Postgres pod at
`/docker-entrypoint-initdb.d/`. The upstream pgvector image runs every
`*.sql` and `*.sh` in that directory ONCE on first boot of an empty
PGDATA, in alphabetical order, as the superuser against the default DB.

## Sync with `infra/postgres/init/`

The canonical copies live in `infra/postgres/init/` — that's what
`docker compose` mounts for local development. The two paths are
duplicated because Helm's `.Files.Get` only reaches inside the chart
directory; we can't reference a sibling path. **Edit both, or sync
from canonical to chart:**

```bash
cp infra/postgres/init/*.sql deploy/helm/scout/files/postgres-init/
```

CI / a pre-commit check could enforce this — for now it's manual.

## Why the SQL hardcodes `'app'` as the password

`02-roles-and-schemas.sql` runs as part of local compose dev, where
the `app` role lives behind a private network and a literal password
is fine. In the chart, `03-set-app-password.sh` ALTERs the role
immediately afterward using the `APP_DB_PASSWORD` env var from the
Secret, so the placeholder never survives a real install.
