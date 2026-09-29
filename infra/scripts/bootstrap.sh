#!/usr/bin/env bash
# infra/scripts/bootstrap.sh — E02-T08
#
# Creates DBs/buckets only; applies no migrations (that is Alembic's job).
# Refuses to run against CHANGE_ME credentials outside the `dev` profile, so
# a stack can never be brought up in a non-dev context with the committed
# placeholder secrets (E02-X01 credential-leakage control).
set -euo pipefail

PROFILE="${1:-dev}"
ENV_FILE="$(dirname "$0")/../compose/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "bootstrap: $ENV_FILE not found — copy infra/compose/.env.example first" >&2
  exit 1
fi

# shellcheck disable=SC1090
set -a; source "$ENV_FILE"; set +a

if [[ "$PROFILE" != "dev" ]]; then
  for var in POSTGRES_PASSWORD GF_SECURITY_ADMIN_PASSWORD MINIO_ROOT_PASSWORD; do
    value="${!var:-}"
    if [[ "$value" == "CHANGE_ME" || -z "$value" ]]; then
      echo "bootstrap: refusing to run profile '$PROFILE' with placeholder $var" >&2
      exit 1
    fi
  done
fi

echo "bootstrap: creating MinIO bucket ${MINIO_BUCKET:-candleviewer-parquet} (if missing)"
docker compose -f "$(dirname "$0")/../compose/docker-compose.yml" \
  --profile cold exec -T minio \
  mc alias set local http://127.0.0.1:9000 "${MINIO_ROOT_USER:-cvminio}" "${MINIO_ROOT_PASSWORD:?}" >/dev/null
docker compose -f "$(dirname "$0")/../compose/docker-compose.yml" \
  --profile cold exec -T minio \
  mc mb --ignore-existing "local/${MINIO_BUCKET:-candleviewer-parquet}"

echo "bootstrap: done (databases created by postgres/questdb image defaults; no migrations applied)"
