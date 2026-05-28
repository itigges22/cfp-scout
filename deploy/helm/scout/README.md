# Scout — Helm chart for OpenShift

Packages Scout (matcher API + bundled SPA + APScheduler + Postgres +
pgvector) for OpenShift. Tuned for an internal team of ~100 users
with headroom to scale to a few hundred without re-architecting.

## What ships

| Workload | Kind | Default replicas | Purpose |
|----------|------|-----------------:|---------|
| `scout-api` | Deployment + HPA | 2 (HPA 2..5) | FastAPI + bundled SPA |
| `scout-scheduler` | Deployment | 1 (singleton) | APScheduler against shared Postgres jobstore |
| `scout-postgres` | StatefulSet | 1 | Postgres 15 + pgvector |
| `scout-migrations` | Job (Helm hook) | runs once per release | `alembic upgrade head` |
| `scout-api` | OpenShift Route | — | TLS-edge external entrypoint |
| `scout-storage` | PVC (RWX) | — | shared `raw_pages` + uploaded PDFs |

All four containerized workloads share a single image
(`quay.io/<org>/scout-api:<tag>`); workload-specific entrypoints are
overridden via `command:` in each Deployment / Job spec.

## Prerequisites

- OpenShift 4.12+ (Routes, SCC restricted-v2)
- A RWX-capable StorageClass (NFS or similar). Ask your cluster admin
  — required when `api.replicas > 1` OR `scheduler.enabled: true`.
- A storage class for Postgres data (RWO is fine; cluster default
  works in most environments).
- A pull secret if `quay.io/<your-org>/scout-api:<tag>` is private.

## Building + pushing the image

The repo's `apps/api/Containerfile` is multi-stage — builds the SPA
from `apps/web/` (stage 1), the Python venv (stage 2), and ships
both in a non-root runtime image (stage 3). Same image used for
api / scheduler / migrations.

```bash
# Build
podman build -f apps/api/Containerfile -t quay.io/your-org/scout-api:2.5.0 .

# Push
podman push quay.io/your-org/scout-api:2.5.0
```

For OpenShift's internal registry instead of Quay:

```bash
podman push --tls-verify=false image-registry.openshift-image-registry.svc:5000/<namespace>/scout-api:2.5.0
```

## Installing

### Step 1 — create the namespace + secrets

```bash
oc new-project scout

# LLM API key (MaaS / OpenAI / whatever you use)
oc create secret generic scout-llm \
  --from-literal=api-key="<your-MaaS-API-key>" \
  --from-literal=embedding-api-key="<embedding-key-or-same-as-above>"

# Database password — chart-generated random password is also an
# option (see secrets.database.createPlaceholder in values.yaml).
oc create secret generic scout-db \
  --from-literal=password="$(openssl rand -base64 32 | tr -d '/+=' | head -c 32)" \
  --from-literal=app-password="$(openssl rand -base64 32 | tr -d '/+=' | head -c 32)"
```

### Step 2 — render + install with operator overrides

```bash
helm upgrade --install scout deploy/helm/scout \
  --namespace scout \
  --set image.tag=2.5.0 \
  --set config.llmBaseUrl=https://litellm-prod.apps.maas.internal/v1 \
  --set route.host=scout.apps.your-cluster.example.com \
  --set sharedStorage.storageClass=ocs-storagecluster-cephfs   # RWX
```

The migrations Job runs first (Helm pre-install hook). Once it
completes, the API + scheduler Deployments roll out. Total install
time: ~2 min on a warm cluster.

### Step 3 — verify

```bash
oc get pods           # all should be Running
oc get route scout    # scout.apps.your-cluster.example.com
helm test scout       # runs the in-cluster smoke test
```

Hit the Route in a browser; you should see the SPA. The dashboard
will be empty until you import messaging docs + run discovery — see
the operator runbook (`docs/ops/runbook.md`).

## Operator-tunable values

| Key | Default | Effect |
|-----|---------|--------|
| `api.replicas` | 2 | Steady-state API replicas (HPA adjusts within bounds) |
| `hpa.enabled` | true | Turn off to pin to `api.replicas` |
| `hpa.maxReplicas` | 5 | Cap on scale-up. Raise for very large teams. |
| `scheduler.enabled` | true | Disable for single-replica installs (set `api.schedulerMode=embedded`) |
| `postgres.storage.size` | 20Gi | Increase as conference corpus grows |
| `sharedStorage.size` | 10Gi | Raw scraped pages + PDF uploads |
| `route.host` | (auto) | Set to your hostname or leave blank for OpenShift auto-host |
| `route.tls.termination` | edge | `edge` / `reencrypt` / `passthrough` |
| `config.llmBaseUrl` | "" | Your MaaS / OpenAI endpoint URL |
| `config.llmChatModel` | llama-scout-17b | Override per your MaaS catalog |
| `monitoring.serviceMonitor.enabled` | false | Opt in if you run user-workload monitoring |

Full surface is documented inline in `values.yaml` — read it before
shipping to prod.

## How upgrades work

```bash
# Build + push a new image
podman build ... -t quay.io/your-org/scout-api:2.6.0 .
podman push quay.io/your-org/scout-api:2.6.0

# Helm upgrade
helm upgrade scout deploy/helm/scout \
  --namespace scout \
  --reuse-values \
  --set image.tag=2.6.0
```

Order on `helm upgrade`:

1. Render new manifests; diff applied
2. Helm `pre-upgrade` hook fires the migrations Job
3. Migrations run; if they fail, the upgrade aborts (no API pods touched)
4. If migrations succeed, API rolling-update + scheduler Recreate-update fire
5. Old pods drain; new ones serve

If you need to roll back:

```bash
helm rollback scout
```

Caveat: rolling back across a destructive migration (column drop,
table rename) is genuinely hard — the new code went out alongside
schema changes that the old code doesn't know about. The chart
can't help with that; treat destructive migrations as one-way.

## Production hardening (when you outgrow the defaults)

### Postgres HA

The default StatefulSet is a single-replica Postgres. For HA + automated
backups + monitoring, swap in the **CrunchyData Postgres Operator**:

1. Install the operator from OperatorHub: `Crunchy Postgres for Kubernetes`
2. Disable the chart's Postgres: `--set postgres.statefulset.enabled=false`
   (you'll need to add this conditional to the chart — it's a 5-line
   change in `templates/postgres-*.yaml`)
3. Create a `PostgresCluster` CR pointing at the same Service name
   `scout-postgres` (so the API's `POSTGRES_HOST` env var keeps
   working). Make sure to enable the `vector` extension in the CR:
   ```yaml
   spec:
     postgresVersion: 15
     extensions:
       - name: vector
   ```

### Backups

Without the operator, take periodic snapshots of the
`scout-postgres-data-0` PVC. Most cloud-native OpenShift clusters
have OADP / Velero available — wire a Schedule resource targeting
the scout namespace.

### Image-pull restrictions

If your cluster requires Red Hat-blessed base images only:
- Build the API image from `registry.access.redhat.com/ubi9/python-312` (already what the Containerfile does ✓)
- Replace the pgvector community image with a custom build:
  ```dockerfile
  FROM quay.io/sclorg/postgresql-15-c9s
  USER 0
  RUN dnf install -y pgvector && dnf clean all
  USER 26
  ```
  Push as `quay.io/your-org/postgres-pgvector:15` and set
  `postgres.image.repository` accordingly.

### SSO integration

Out of scope for this chart — Red Hat SSO (Keycloak) integration is
a follow-up. Today the chart ships with no auth on the API. Run
behind your cluster's network policy / IP allowlist until SSO lands.

## Troubleshooting

### Migrations Job stuck

```bash
oc logs job/scout-migrations
```

Common cause: Postgres pod not ready yet. The Job's init container
runs `pg_isready` against the headless service before alembic
fires — if it loops forever, check `oc describe statefulset
scout-postgres` and the data PVC's binding.

### API pods CrashLoopBackOff

```bash
oc logs deploy/scout-api --previous
```

Usual suspects:
- Bad `LLM_BASE_URL` in the ConfigMap → matcher init fails on first chat call
- Missing `scout-llm` Secret keys → readiness probe fails
- Migrations didn't apply → first DB query errors out

### Scheduler pod running but jobs aren't firing

```bash
oc exec deploy/scout-scheduler -- python -c \
  "from app.scheduler import get_scheduler; print(get_scheduler().get_jobs())"
```

If `get_jobs()` is empty, the scheduler started before any jobs were
registered. Restart it: `oc rollout restart deploy/scout-scheduler`.

### Two scheduler instances competing

Symptom: same job fires twice in quick succession. Either:
- Two `scout-scheduler` pods accidentally got scheduled (check
  `oc get pods` — there should be exactly one)
- An API pod has `SCHEDULER_MODE=embedded` instead of `disabled`
  (check `oc set env deploy/scout-api --list | grep SCHEDULER`)

## Image tag conventions

| Tag pattern | Use |
|-------------|-----|
| `2.5.0` | Pin to a specific release |
| `2.5` | Pin to a minor (auto-updates on patch) |
| `latest` | Dev only — never use in prod (it breaks rollback) |
| `git-<sha>` | CI-tagged builds; use for non-production environments |
