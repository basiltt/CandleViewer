# `deployments/ledger.jsonl`

Append-only audit log of dev/staging deploy attempts (E03-T09 "Deployment
records"). One JSON object per line, appended by `tools/ci/deploy_dev.py`
and committed by `.github/workflows/deploy-dev.yml` /
`deploy-staging.yml`. This is a stopgap for auditability until E04's
observability stack lands a proper deploy-events store — do not build new
tooling against this file's shape without checking `tools/ci/deploy_dev.py`
first, since it is the single writer.

## Schema

| field | type | meaning |
|---|---|---|
| `sha` | string | git sha the digest was built from (`"rollback"`/`"unknown"` for some rollback paths where the original sha is not carried forward) |
| `digest` | string | `sha256:...` image digest deployed |
| `environment` | `"dev" \| "staging"` | which stack |
| `actor` | string | GitHub Actions actor that triggered the run |
| `timestamp` | string | UTC ISO-8601 |
| `outcome` | string | one of `success`, `signature-verification-failed`, `smoke-failed`, `sha-mismatch`, `rolled-back` |
| `duration_s` | number | wall-clock seconds for this attempt |
| `detail` | string | free-text context (error message, rollback source digest) |

The first line is a seed row (`sha: "0"`) so this file is non-empty and
tracked from creation; it is not a real deploy and tooling should not treat
it as one (it uses the all-zero placeholder digest, never a real one).

No `UPDATE`/`DELETE` — only appends. Never hand-edit; if a bad row needs
correcting, append a new row explaining the correction instead (mirrors the
audit-table append-only rule, C-5.7, applied here by convention since this
is a file, not a DB table).
