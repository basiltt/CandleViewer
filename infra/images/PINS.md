# Container image pin ledger

Digests are real registry manifest (index) digests, resolved anonymously over the registry v2 HTTP
API by `tools/ci/resolve_image_digests.py` on 2026-10-06 and verified in CI with `--check`
(#1857, fixes #1538 #1586). Refresh: edit the tag, replace the digest with any placeholder, run the
script without flags.

| Image:tag                     | Digest                                                                  | Registry   |
| ----------------------------- | ----------------------------------------------------------------------- | ---------- |
| postgres:16.4                 | sha256:e62fbf9d3e2b49816a32c400ed2dba83e3b361e6833e624024309c35d334b412 | Docker Hub |
| questdb/questdb:8.1.1         | sha256:82ef61a3919f4014e2aae1216f2803288b176a54c197d0933863bdc8c04a2e03 | Docker Hub |
| grafana/grafana:11.2.0        | sha256:408afb9726de5122b00a2576763a8a57a3c86d5b0eff5305bc994ceb3eb96c3f | Docker Hub |
| prom/prometheus:v2.54.1       | sha256:f6639335d34a77d9d9db382b92eeb7fc00934be8eae81dbc03b31cfe90411a94 | Docker Hub |
| bitnamilegacy/minio:2024.9.13 | sha256:8a92f71856f4b4b5755fa6afe4e7f9d0db7e18c889318f6772cb342d9b13470d | Docker Hub |

Other pinned refs (python, alertmanager, pushgateway, zaproxy, trufflehog) were verified to exist
by `--check` and left unchanged.

minio: `minio/minio:RELEASE.2024-09-13T20-26-02Z` is no longer anonymously served on Docker Hub or
quay.io (#1586). Nearest published equivalent is the same-date build `bitnamilegacy/minio:2024.9.13`
(data dir `/bitnami/minio/data`, console port via `MINIO_CONSOLE_PORT_NUMBER`).
