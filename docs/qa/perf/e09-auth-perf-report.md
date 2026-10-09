# E09 auth perf and chaos report (E09-Q05, #296)

Status: **harness delivered; k6 numbers pending CI/nightly run.** k6 and the docker compose
stack are not available on the authoring machine, so no latency figure below was measured.
No number in this file is invented.

## Reference host and Argon2id

- Reference host spec: pending CI/nightly run (record CPU, RAM, kernel at run time).
- Argon2id in force: `DEFAULT_ARGON2_PARAMS` = m=65536 KiB (64 MiB), t=3, p=4
  (`candleviewer/auth/hashing.py`). `tests/load/k6/auth.js` `setup()` aborts if below this floor.

## Budgets

| Budget | Source | Measured | Verdict |
|---|---|---|---|
| `GET /auth/session` p95 <= 100 ms, warm cache | #13 | pending CI/nightly run | pending |
| `GET /auth/session` cold-cache p95 | reported only | pending CI/nightly run | pending |
| `POST /auth/step-up` p95 <= 400 ms | SCR-006 | pending CI/nightly run | pending |
| `POST /auth/mfa/verify` p95 <= 400 ms | SCR-002 | pending CI/nightly run | pending |
| Argon2id step p50 >= 100 ms | SR-011 | pending CI/nightly run | pending |
| Negative control (`CV_CACHE_DISABLED=1`) fails bootstrap budget | ticket | pending | pending |

## Chaos outcomes (`services/api/tests/chaos/auth/`, `-m "chaos and integration"`)

C-13.6 mapping: #10 (datastore outage), #6 (clock drift); the rest are auth-specific.

| Scenario | Local result (in-process fakes, Python 3.14) |
|---|---|
| Postgres restart (fail closed, recover) | pass |
| Postgres restart vs compose stack | skipped locally (no docker); runs in CI |
| Clock skew +-1 accepted, +-3 rejected | pass |
| WS gateway restart, no carried auth state | pass |
| Revocation storm (100 sockets, `bye`/4401) | pass |
| Session-store pressure with sweeper | pass |

## Not covered yet (follow-ups)

- Rate-limit / lockout race under load (SR-015/016) and the "skew raises a system event" check
  need the staging stack; not implemented in this PR.
- The k6 script degrades truthfully: the Argon2 param-floor check and step timing are skipped with a logged note while the backend lacks `Server-Timing: argon2` and `/auth/_perf/argon2-params` (set `CV_ARGON2_TIMING=1` once they exist).
