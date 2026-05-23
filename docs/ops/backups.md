# Backups and restore

How to snapshot Scout's Postgres data and restore from a snapshot. Backups
are the **only** justified host bind mount in the project — everything else
runs through named volumes.

For schema/role context, see [`database.md`](database.md).

## Commands

```bash
make db-dump                                  # dump to ./backups/scout-<timestamp>.sql.gz
make db-restore FILE=./backups/scout-...sql.gz   # restore (prompts to confirm)
```

## What gets dumped

`pg_dump` runs **inside the postgres container** against the database named
by `POSTGRES_DB`. The dump is plain SQL with these flags:

- `--no-owner` — strips role ownership so the dump restores under any user
- `--no-privileges` — strips GRANTs (role setup is re-applied via init SQL)
- `--clean --if-exists` — restore drops existing objects first, idempotent

The output is piped through `gzip` to `./backups/scout-<YYYY-MM-DD-HHMMSS>.sql.gz`
on the host. Typical sizes:

| Scale | Compressed size |
|-------|-----------------|
| Empty post-migration | <100 KB |
| ~100 conferences + matches | <5 MB |
| ~1,000 conferences + full embeddings | 50-200 MB |

## What does NOT get dumped

- `postgres_data` volume metadata (statistics, WAL position, etc.)
- Stored PDFs and raw scraped HTML — these live in the `pdf_uploads` and
  `scraper_raw_pages` named volumes, not in the database. To back them up,
  use Docker/Podman's volume tooling (e.g. `docker run --rm -v pdf_uploads:/d -v $(pwd)/backups:/b alpine tar czf /b/pdf_uploads.tar.gz -C /d .`).
  This is not yet wired into the Makefile; flag a request if it becomes painful.
- The LLM API key (`.env` lives on the host, not the volume — never include it in a dump destined for sharing)

## Restoring

```bash
make db-restore FILE=./backups/scout-2026-05-21-143000.sql.gz
```

The command prompts for confirmation (type `restore`) because it **destroys
the current data** via the `--clean` flag in the dump. Restoring then:

1. Connects as the superuser inside the container
2. `gunzip`s the file and pipes the SQL through `psql`
3. `--set ON_ERROR_STOP=1` aborts on the first SQL error rather than silently skipping

If restore fails partway, the database is in an indeterminate state.
Recovery: `make nuke && make up && make db-restore FILE=...`.

## Round-trip test (verify your backups work)

Do this once when you set up; do it again before any risky operation:

```bash
make db-dump
# capture the filename, e.g. backups/scout-2026-05-21-143000.sql.gz

# Destroy everything
make nuke
make up
# wait for postgres healthy (a few seconds)

make db-restore FILE=./backups/scout-2026-05-21-143000.sql.gz
```

If the restore succeeds and the dashboard shows the same data after a
browser refresh, the backup pipeline works. **A backup you've never
restored from is not a backup.**

## Retention

The `./backups/` directory is gitignored. Manage retention yourself:

```bash
# Keep the 7 most recent dumps
ls -1t backups/scout-*.sql.gz | tail -n +8 | xargs rm -f
```

For automated nightly backups, add a cron entry on the host that calls
`make db-dump` and prunes old files. We don't currently ship a built-in
scheduler for backups; the user owns this.

## Restoring to a different machine

The dump is portable across hosts as long as the destination has:
- Same major Postgres version (16)
- Same extensions installed (the init SQL handles this on first boot)
- Same schemas (the init SQL handles this on first boot)

So the workflow is:

```bash
# on the source host
make db-dump
# copy backups/scout-...sql.gz to the destination host

# on the destination host (first time setup)
git clone https://github.com/<org>/scout
cd scout
cp .env.example .env   # edit LLM key
make up                # postgres boots, init SQL runs
make db-restore FILE=./backups/scout-...sql.gz
```

## Troubleshooting

### "Dump file is empty"
postgres container isn't running. `make up` first.

### "permission denied" on restore
The dump was created with `--owner` (i.e. by an older copy of `make db-dump`).
Either regenerate the dump or edit out the `ALTER ... OWNER TO` lines:

```bash
gunzip -c old-dump.sql.gz | grep -v 'ALTER .* OWNER TO' | gzip > fixed-dump.sql.gz
```

### Restore is slow
Big embedding tables take a while because the HNSW index has to rebuild on
restore. There's no faster path without dump-format trickery; ride it out.

## See also

- `Makefile` — `db-dump`, `db-restore` targets
- [`database.md`](database.md) — Postgres schemas + roles this backs up
