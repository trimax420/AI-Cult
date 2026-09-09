#!/usr/bin/env sh
set -eu
export MODEL_LOCATION="${MODEL_LOCATION:-global}"
export GEMINI_MODEL="${GEMINI_MODEL:-gemini-3.8-flash}"

required="PROJECT_ID PROJECT_NUMBER REGION ARTIFACT_REPOSITORY SERVICE_ACCOUNT IMAGE_TAG GRAFANA_URL GRAFANA_CLOUD_OTLP_ENDPOINT GRAFANA_PROMETHEUS_DATASOURCE_UID GRAFANA_LOKI_DATASOURCE_UID GRAFANA_TEMPO_DATASOURCE_UID GEMINI_MODEL"
for name in $required; do
  eval "value=\${$name:-}"
  if [ -z "$value" ]; then
    echo "Missing required environment variable: $name" >&2
    exit 1
  fi
done

manifest="$(mktemp)"
trap 'rm -f "$manifest"' EXIT
envsubst < "$(dirname "$0")/cloudrun-service.yaml.template" > "$manifest"
if [ "${1:-}" = "--dry-run" ]; then
  cat "$manifest"
else
  gcloud run services replace "$manifest" --region "$REGION" --project "$PROJECT_ID"
fi
