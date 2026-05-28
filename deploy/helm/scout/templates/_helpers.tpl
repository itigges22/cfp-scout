{{/*
Helpers shared by every template. Keep this small — Helm's templating
gets unreadable fast when helpers wrap helpers wrap helpers.
*/}}

{{/* Resource name prefix. Honors fullnameOverride / nameOverride. */}}
{{- define "scout.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{ .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{ .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else -}}
{{ printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end -}}
{{- end -}}
{{- end -}}

{{/* Chart label — version + name for resource-management tooling. */}}
{{- define "scout.chart" -}}
{{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end -}}

{{/* Standard labels every resource carries — matches recommendations
     from kubernetes.io/docs/concepts/overview/working-with-objects/common-labels/. */}}
{{- define "scout.labels" -}}
helm.sh/chart: {{ include "scout.chart" . }}
app.kubernetes.io/name: {{ default .Chart.Name .Values.nameOverride }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- with .Values.commonLabels }}
{{ toYaml . }}
{{- end }}
{{- end -}}

{{/* Selector labels — the subset of labels used to pin
     Deployments→Pods + Services→Pods. MUST be immutable across
     upgrades, hence why this is a separate helper. */}}
{{- define "scout.selectorLabels" -}}
app.kubernetes.io/name: {{ default .Chart.Name .Values.nameOverride }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/* Per-component labels. ``.component`` is set by the caller via a
     ``dict`` (e.g. ``include "scout.componentLabels" (dict "ctx" . "component" "api")``). */}}
{{- define "scout.componentLabels" -}}
{{ include "scout.labels" .ctx }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{- define "scout.componentSelectorLabels" -}}
{{ include "scout.selectorLabels" .ctx }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{/* Image reference. Tag defaults to .Chart.AppVersion when blank. */}}
{{- define "scout.image" -}}
{{- $tag := default .Chart.AppVersion .Values.image.tag -}}
{{ printf "%s:%s" .Values.image.repository $tag }}
{{- end -}}

{{/* ServiceAccount name. Honors serviceAccount.name override. */}}
{{- define "scout.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{ default (include "scout.fullname" .) .Values.serviceAccount.name }}
{{- else -}}
{{ default "default" .Values.serviceAccount.name }}
{{- end -}}
{{- end -}}

{{/* Postgres host — used by API + scheduler to connect to the
     in-cluster Postgres StatefulSet via its headless service. */}}
{{- define "scout.postgresHost" -}}
{{ include "scout.fullname" . }}-postgres
{{- end -}}

{{/* Database URL the API + scheduler use. asyncpg dialect because
     the codebase is fully async. Connects as the restricted ``app``
     role (NOT the superuser). The role is created by the Postgres
     init script ``02-roles-and-schemas.sql`` and has its password
     aligned to the Secret by ``03-set-app-password.sh`` on first boot.
     Both scripts live in the postgres-init ConfigMap. */}}
{{- define "scout.databaseUrl" -}}
postgresql+asyncpg://app:$(APP_DB_PASSWORD)@{{ include "scout.postgresHost" . }}:5432/{{ .Values.postgres.databaseName }}
{{- end -}}

{{/* Common pod-spec snippets — pulled out so api/scheduler/migrations
     all use the same security context, image pull secrets, etc. */}}
{{- define "scout.podSecurityContext" -}}
{{- with .Values.podSecurityContext }}
securityContext:
{{ toYaml . | indent 2 }}
{{- end }}
{{- end -}}

{{- define "scout.containerSecurityContext" -}}
{{- with .Values.containerSecurityContext }}
securityContext:
{{ toYaml . | indent 2 }}
{{- end }}
{{- end -}}

{{- define "scout.imagePullSecrets" -}}
{{- with .Values.image.pullSecrets }}
imagePullSecrets:
{{ toYaml . }}
{{- end }}
{{- end -}}

{{/* Shared env injected on every API/scheduler/migrations container.
     ConfigMap supplies the non-secret env; Secret refs supply the
     sensitive ones (LLM api key, DB password). */}}
{{- define "scout.commonEnvFrom" -}}
envFrom:
  - configMapRef:
      name: {{ include "scout.fullname" . }}-config
{{- end -}}

{{- define "scout.commonSecretEnv" -}}
- name: APP_DB_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ .Values.secrets.database.name }}
      key: {{ .Values.secrets.database.appPasswordField }}
- name: POSTGRES_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ .Values.secrets.database.name }}
      key: {{ .Values.secrets.database.passwordField }}
- name: LLM_API_KEY
  valueFrom:
    secretKeyRef:
      name: {{ .Values.secrets.llm.name }}
      key: {{ .Values.secrets.llm.apiKeyField }}
{{- if .Values.secrets.llm.embeddingApiKeyField }}
- name: LLM_EMBEDDING_API_KEY
  valueFrom:
    secretKeyRef:
      name: {{ .Values.secrets.llm.name }}
      key: {{ .Values.secrets.llm.embeddingApiKeyField }}
      optional: true
{{- end }}
- name: DATABASE_URL
  value: {{ include "scout.databaseUrl" . | quote }}
{{- end -}}
