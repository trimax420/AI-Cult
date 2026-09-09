#!/usr/bin/env sh
set -eu
# Build locally without pushing images or deploying a service.
root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
tag="${IMAGE_TAG:-cloudrun}"
prefix="${IMAGE_PREFIX:-ai-cult}"
docker buildx build --platform linux/amd64 --load -t "$prefix-simulator:$tag" -f "$root/simulator/Dockerfile" "$root/simulator"
docker buildx build --platform linux/amd64 --load -t "$prefix-agent:$tag" -f "$root/production_director_agent/Dockerfile" "$root"
docker buildx build --platform linux/amd64 --load -t "$prefix-dashboard:$tag" -f "$root/operator-dashboard/Dockerfile" "$root/operator-dashboard"
