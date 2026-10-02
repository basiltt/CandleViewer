# E07-Q04 storage chaos: handoff (E45 baselines, E07-X02 controls, E48 runbook notes)

Scenarios live in `services/api/tests/chaos/storage/`. S3-S9 run everywhere (in-process
fakes + exporter crash hooks); S1, S2, S3b need docker compose and a loopback image and
skip unless `CV_CHAOS_DOCKER=1`. Docker is not available on the authoring machine, so S1/S2/S3b
were **not run locally**; the nightly job is their first execution.

## Recovery-time baselines (for E45)
No measured numbers exist yet (no docker locally). The docker scenarios record
`t_restart_to_ok` (container restart -> `storage_tier_health` ok) and `t_drain`
(restart -> buffered batch flushed). The first nightly run populates the table below;
until then E45 must treat these as UNMEASURED, not zero.

| Scenario | t_restart_to_ok | t_drain |
|---|---|---|
| S1 QuestDB down | TBD (first nightly) | TBD |
| S2 Postgres down | TBD (first nightly) | n/a |

## Control verification results (input to E07-X02)
- SR-096 (disk guard, trading unaffected): S3 (in-process) + S3b (loopback, Postgres write during full volume).
- SR-094 (checksum/quarantine): S7. SR-099 (no double delete/audit): S8 - reaper serialises per
  volume in-process and re-checks partition existence before drop (stale plan is a no-op).
- Known limit: the S8 lock is per-process; cross-process safety relies on the existence re-check.

## Runbook notes (feeds E48)
- **QuestDB down:** expect `/readyz` degraded, `questdb_write_errors_total` rising, bounded buffer
  backpressure; restart QuestDB, buffer flushes once (dedup). Do not restart the API.
- **Disk full:** critical event precedes any deletion; pinned data untouched; free space above 25%
  to resume recording. Trading (Postgres) is on a separate volume.
- **Export verify failed:** CRITICAL `system_events`, run aborted, nothing dropped; inspect the
  manifest vs hot row counts, fix cause, re-run export.

## Waiver
Owner waiver for docker-gated scenarios running only nightly: to be recorded on #275 by the owner.
