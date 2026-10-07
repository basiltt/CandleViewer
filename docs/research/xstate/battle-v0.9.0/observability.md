# Battle v0.9.0 — OBSERVABILITY track (round-13 re-verification)

Library `_ref/xstate-statemachine`: tag `v0.9.0` = `91bd979`; `main` is 2
commits ahead of the tag by `.github/workflows/publish.yml` only (CI
publish-smoke-test) — confirmed via `git diff v0.9.0..HEAD --stat`
(`1 file changed, 14 insertions(+), 1 deletion(-)`). `__version__ ==
"0.9.0"`. Not yet on PyPI. Fresh venv on `main`, run with the pinned
`.venv-main` interpreter.

Background full-suite run (`suite-v0.9.0.log`) completed independently
during this task: **3577 passed, 13 skipped, 92.86% coverage, no
failures** — consistent with the standalone findings below.

Standalone script: `battle-v0.9.0/observability/attacks.py` (stdlib +
`xstate_statemachine` only, neutral cwd `<home>`, pinned venv).
**Time-boxed severely**: this session had to spend most of its budget on
environment/diff verification and API-shape discovery (the v0.9.0
`scheduled_sends` restore record is flat `{"type", "data",
"remaining_ms"}`, not the nested `{"event": {...}}` shape a first draft
assumed; `on_invalid_event(interpreter, error, raw_event)` order was
verified against `plugins.py` directly). Only **2 of the ~10 requested
new-attack categories** were implemented and run to completion; the rest
are listed under Not Covered.

## Prior-defect re-run

**Not performed this round.** The round-12 script
(`battle-de2da4e/observability/attacks.py`, the most recent prior artefact
for this track) was not re-executed against `v0.9.0` in this session;
time was consumed by environment verification (diffstat, changelog read,
suite tail) and the two new attacks below. This is a **gap**, not a
"no regressions found" claim — see Not Covered.

## New attacks run

**A — v3 latch fields (`chain_trips` / `last_chain_error`) round-trip
across 5 restarts, `RestoredError` message intact, counter monotonic.**
`maxIterations: 3` self-chained `LAP` cycle trips the chain-budget latch
once (`chain_trips == 1`), then the snapshot is restored 5 times in
sequence (restore → assert same count + `RestoredError` with detail intact
→ re-trip → re-persist → restore again). **PASS**: monotonic to
`chain_trips == 6` after 5 restart+re-trip cycles, `RestoredError`
carries `"exceeded ... chained ..."` detail at every restore, `isinstance`
check holds every time (async engine, `def` actions only — `async def`
action variant and the sync engine were **not** covered this round).

**B — `strict` + schemas apply to restored `scheduled_sends`, 300
trials.** Reproduces the exact #227 shape: a `strict: True` machine is
snapshotted, then a forged parked `scheduled_sends` record with an
undeclared type (`"EVIL"`) is spliced in alongside a genuine declared
record (`"GOOD"`), and the blob is restored fresh with a plugin attached
via `from_snapshot(...)` + `.use()` before `start()`. **PASS, 300/300**:
every trial reports the forged `EVIL` record via `on_invalid_event`
(error + raw event visible to the plugin, exactly once per trial), the
interpreter's `status` stays `"running"` (not corrupted or hung) after
the refusal, and no trial silently admitted the undeclared type. Met the
requested ≥300 floor. Async engine, `def` actions only — the requested
`plugins=` *constructor* kwarg (as opposed to `.use()` on the restored
instance) was **not** separately exercised, so the "receives every
restore-time hook exactly once via `from_snapshot(plugins=...)`" framing
in the task is only partially covered (this attack used `.use()` after
`from_snapshot`, not the `plugins=` kwarg itself — the changelog states
both reach `on_invalid_event` identically, but that equivalence was not
independently re-verified here).

Wall clock for both attacks together: **~19.6 s** (well under the 120 s
per-script bound).

## Defects found

**None.** Both executed attacks passed against the documented #226/#227
contract. No `D13-observability-n` entries are raised this round.

## Not covered (time-boxed out — do not read as clean)

- **Prior-defect re-run**: round-12's `battle-de2da4e/observability/`
  script was not re-executed against `v0.9.0` at all this round — no
  FIXED/STILL-PRESENT/CHANGED/SUPERSEDED table was produced. This is the
  single largest gap versus the task's ask.
- `plugins=` constructor kwarg on `from_snapshot` specifically (vs.
  `.use()` after restore) — not isolated.
- Sync engine and `async def` action-body variants of attacks A/B.
- Concurrency: 200 machines × action-spawned workers outliving them; 100
  concurrent `ensure_future` hand-outs; def-service `send()` task
  identity under executor; where the #232 `RuntimeWarning` surfaces
  under `-W error` inside asyncio — none attempted.
- Fuzzing: livelock fuzzer (≥500 configs); config fuzzer incl.
  inline-dict `invoke.src` → `InvalidConfigError` — none attempted (the
  import list even pulled in `InvalidConfigError` and `ReentrantWaitError`
  for this purpose but neither was exercised before time ran out).
- Determinism: 50× trace comparisons both engines both kinds — not run.
- Security: forged `chain_trips`/`last_chain_error` in the v3 blob framed
  as a trust-boundary question (attack A used only genuine values) — not
  attempted as an adversarial forgery.
- Soak: the 12-minute, 200-machine, action-spawned-workers, heartbeat,
  chaos-restore soak was not attempted at all.
- Semantics: task-identity matrix (action→helper→send,
  action→task→send, etc.) vs. internal/external — not attempted.

## Verdict

**Partial, materially incomplete confirmation.** The two new attacks that
were run (v3 latch round-trip across restarts; strict/schema enforcement
on restored `scheduled_sends` at 300 trials) both PASS cleanly and are
consistent with the #226/#227 changelog claims and the clean background
suite run (3577 passed, 92.86% coverage). However, this round did **not**
re-run the round-12 prior-defect script against `v0.9.0` (no regression
table), and covered only 2 of the roughly 10 requested new-attack
categories (persistence latch + strict-restore; no concurrency, no
fuzzing, no determinism, no soak, no security-forgery, no semantics
matrix). Treat this as a narrow green data point on the two specific
persistence contracts checked, not a track-level clearance.
