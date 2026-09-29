#!/usr/bin/env bash
# infra/scripts/healthcheck.sh — E02-T08
#
# Polls `docker compose ps` until every service in the given profile set is
# reported healthy (or the timeout elapses), then exits 0/1. Used by `make
# up` (via docker compose's own `condition: service_healthy` depends_on) and
# directly by the integration test that drives the ticket's acceptance
# criterion 1 ("all six services reach healthy within 120 seconds").
set -euo pipefail

COMPOSE_FILES=(-f "$(dirname "$0")/../compose/docker-compose.yml")
PROFILES=("${@:-core obs cold}")
TIMEOUT_S="${HEALTHCHECK_TIMEOUT_S:-120}"
INTERVAL_S=3
elapsed=0

profile_args=()
# shellcheck disable=SC2206
for p in ${PROFILES[@]}; do
  profile_args+=(--profile "$p")
done

while (( elapsed < TIMEOUT_S )); do
  unhealthy=$(docker compose "${COMPOSE_FILES[@]}" "${profile_args[@]}" ps --format '{{.Health}}' \
    | grep -v -E '^(healthy|)$' || true)
  if [[ -z "$unhealthy" ]]; then
    echo "healthcheck: all services healthy after ${elapsed}s"
    exit 0
  fi
  sleep "$INTERVAL_S"
  elapsed=$((elapsed + INTERVAL_S))
done

echo "healthcheck: timed out after ${TIMEOUT_S}s waiting for services to be healthy" >&2
docker compose "${COMPOSE_FILES[@]}" "${profile_args[@]}" ps >&2
exit 1
