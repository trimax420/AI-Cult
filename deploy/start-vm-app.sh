#!/usr/bin/env bash
set -euo pipefail
cd /opt/reelwarden
test -f bootstrap-ready
umask 077
if ! test -f .env; then
  project_id=$(curl -fsS -H 'Metadata-Flavor: Google' http://metadata.google.internal/computeMetadata/v1/project/project-id)
  public_ip=$(curl -fsS -H 'Metadata-Flavor: Google' http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip)
  {
    printf 'GOOGLE_GENAI_USE_VERTEXAI=TRUE\nGOOGLE_CLOUD_PROJECT=%s\n' "$project_id"
    printf 'GOOGLE_CLOUD_LOCATION=global\nGEMINI_MODEL=gemini-3.8-flash\nENABLE_PORTFOLIO_DEMO=true\n'
    printf 'GRAFANA_PUBLIC_URL=http://%s:3000/d/ai-production-director/reelwarden-c2b7-production-observability\n' "$public_ip"
    printf 'GRAFANA_ADMIN_PASSWORD=%s\n' "$(openssl rand -hex 24)"
    printf 'GRAFANA_MCP_AUTH_TOKEN=%s\n' "$(openssl rand -hex 32)"
  } > .env
fi
export COMPOSE_PARALLEL_LIMIT=1
docker compose -f docker-compose.yml -f docker-compose.vm.yml --profile agent config --quiet
docker compose -f docker-compose.yml -f docker-compose.vm.yml --profile agent up -d --build
docker compose -f docker-compose.yml -f docker-compose.vm.yml --profile agent ps -a
