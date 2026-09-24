# Determinism battle track — v0.9.0/main (round-12 re-verification)

## 0. Bottom line

`main` is 2 commits ahead of `v0.9.0` (CI-only: `.github/workflows/publish.yml`,
+14/-1, no source change — confirmed via `git diff v0.9.0..HEAD --stat`).
Package is **not yet on PyPI** (`pip download xstate_statemachine==0.9.0`
would fail; not attempted here per the environment note — flagging, not a
defect). Fresh venv on `main`, full suite already green in the background
(`suite-v0.9.0.log`): **3577 passed, 13 skipped, 0 failed, 92.86% coverage**
(gate floor 90%), 597.15s.

Re-ran the inherited `d`/`e`/`f`/`g`/`h`/`i`/`n` determinism corpus
(`battle-de2da4e/determinism/`) spot-checked on `main`: **all still STABLE**,
no SUPERSEDED cases. None of the `wait=True`-using scripts (`d1_replay.py`,
`d2_receipt_deferred.py`, `f5_nested_parallel_snapshot_refusal.py`) trip the
`RuntimeWarning` #232 added, because all three await the receipt from
*outside* a running step (the harness driving the interpreter), not from a
`def` action that drops it — the shape #232 targets. See §1.

New attacks this pass (§3) target round-12's own persistence surface
(#226/#227/#230): the `chain_trips`/`last_chain_error` v3 latch across N
restarts, `strict`-refused `scheduled_sends` admitted mid-restore as a
property (40 trials, randomised payload shapes), and `plugins=` receiving
every restore-time `on_invalid_event` hook exactly once. **All pass; no new
`D13-determinism-n` defects are raised this pass.**

Time-boxed out this pass (script/task wall-clock bounds): the 200-machine
soak, the def-action `RuntimeWarning` surfacing-location probe, the
task-identity matrix (#225), the livelock/config fuzzers at scale, and the
BENCH-6 timer-lateness distribution — see §4.

## 1. Prior-defect re-run table (spot-check on `main`)

| Script | Verdict | Notes |
|---|---|---|
| `f1_chain_vs_external.py` | STABLE | Chain budget still trips (`RunawayChainError`), `last_error` reflects it, ~287 external sends accepted around the trip — same shape as round 11. |
| `n5b_corrupt_escapes.py` | STABLE | 0/9 malformed-snapshot shapes escape as anything but `SnapshotCorruptError`; error text now also names `scheduled_sends` in the same shape-check message family (consistent with #227's shared `_admit_restored`/shape-check path). |
| `i2_v2_upcast_forgery.py` | STABLE | v2-forged `done`/`error-platform` still upcast and fire; v3-forged equivalents still refused (`fired = 0`). |
| `d1_replay.py` / `d2_receipt_deferred.py` / `f5_nested_parallel_snapshot_refusal.py` | STABLE, no SUPERSEDED | All three use `wait=True` from the *driver* awaiting the interpreter's own receipt outside a running step — not the in-action reentrant shape #219 (or the new #232 `def`-action-drops-receipt shape) targets. Re-audited call sites on `main`; unchanged conclusion. |

Not individually re-run this pass (time-boxed): `d3`..`d10b`, `e1`, `f4`,
`g1`, `g6`, `h1`, `h2`, `i1`, `n6` — no code path they exercise changed in
the round-12 changelog, and the full suite (which supersets their
assertions in spirit) is green. Treat as carried-forward STABLE, not
independently re-verified this pass.

## 2. New attacks this pass — `k1_persist_round12.py`

Single standalone script, both properties on the async engine (chosen
because #226/#227/#230 are engine-symmetric per the changelog; the sync
engine's own restore path is exercised by `d10b`/`h2` already).

### 2.1 (a) `chain_trips` / `RestoredError` monotonic across N restarts

Machine: one state, `GO` both bumps context and re-raises `GO`
(`{"type": "raise", "params": {"event": "GO"}}`), so a single external `GO`
is a genuine in-step self-chain that trips the 1000-event chain budget.

Loop: trip once, snapshot, restore, assert `chain_trips` and
`last_chain_error` (as `RestoredError`, message-equal to the pre-persist
string) survive; `start()`; trip again; snapshot again — repeated 3 times.

**Result: PASS.** `chain_trips` observed strictly increasing across the 3
restart cycles (final count 4 — 1 initial trip + 3 post-restore re-trips),
`RestoredError` message identical to the original latch string at every
hop, and `d.get("chain_trips")`/`d.get("last_chain_error")` in the
persisted dict agree with the live interpreter's `chain_trips` /
`last_chain_error` before every persist call. Matches #226 exactly.

### 2.2 (b) `strict`-refused `scheduled_sends` mid-restore — property, 40 trials

`strict: True` machine. Each trial arms a `raise(delay=)` self-send via
`TYPED` (which itself does not chain), takes a snapshot, then **injects** a
synthetic `scheduled_sends` list mixing a strict-illegal record
(`type: NOT_A_REAL_TYPE_<n>`) and a legal one (`type: GO`), varying the
count (1–4 records, sampled with repetition) and delay across a seeded
`Random(7)`. Restores with a `CountingPlugin` registered via
`plugins=[...]`, then `start()`s.

**Result: PASS, 40/40.** Every trial ends in a legal running configuration
(`_configuration_is_legal()` true, or `status != "running"`), and
`plugin.invalid_count` equals exactly the number of illegal records
injected in that trial (varies 0–3 across trials) — confirming (per §2.3
below) the hook fires once per refused record and admission of the
`scheduled_sends` lane goes through `_admit_restored` exactly as #227
describes. One correction made while writing the harness: `_admit_restored`
for `scheduled_sends` runs inside `_rearm_restored_self_sends`, called from
`start()`, not from `from_snapshot()` itself — so the plugin count must be
read after `await i2.start()`, not immediately after construction. Not a
defect; a harness-timing detail worth recording since the docstring's
"restore-time" language could otherwise be misread as "during
`from_snapshot()`".

### 2.3 (c) `plugins=` sees every restore-time `on_invalid_event` exactly once

Same 40-trial run as §2.2 doubles as this property: `CountingPlugin`
(passed via `from_snapshot(..., plugins=[plugin])`) is the *only* observer
registered, and its count is asserted equal to the bad-record count on
every trial — i.e. one hook firing per refused record, zero for the legal
ones, with no double-count and no miss across 40 randomised shapes.
**PASS.**

## 3. Not covered this pass (explicit gaps against the brief)

Time-boxed (script ≤120s / task ≤20min):

- **Task-identity matrix (#225)**: action→helper→send,
  action→task→send, action→task→task→send, def-service→send,
  child→parent send, after-handler→send, vs. expected internal/external
  routing. Not attempted.
- **`def`-action `RuntimeWarning` (#232)** surfacing location under
  `-W error` inside asyncio — not probed; none of the re-run `wait=True`
  scripts exercise the dropped-receipt shape (confirmed by inspection, not
  by a dedicated repro).
- **200-machine / action-spawned-worker concurrency probe (#225's
  `ensure_future` hand-out shape at scale)** and the **12-minute soak**.
- **Livelock fuzzer ≥500 configs** and the **config fuzzer's inline-dict
  `invoke.src` → `InvalidConfigError` variant (#231)** — spot-checked
  conceptually via the changelog/tests but no standalone repro written this
  pass.
- **Forgery of `chain_trips`/`last_chain_error` in a v3 blob** — a
  trust-boundary framing exercise (only interesting if it crosses a
  documented boundary; `from_snapshot` already treats the whole payload as
  trusted input per its own docstring, so this would likely be a
  non-finding, but was not run to confirm).
- **BENCH-6**: `benchmarks/production_characteristics.py --quick` ×5 —
  not run this pass; no timer-lateness distribution collected.
- **50× cross-engine determinism traces including `chain_trips`** — only
  the async engine was exercised in §2; no cross-engine diff was taken.

## 4. Verdict

Inherited determinism-track defects remain FIXED on `main`/v0.9.0 baseline
(spot-checked subset, §1); no SUPERSEDED cases. New round-12 persistence
attacks (§2) — the `chain_trips`/`RestoredError` latch across repeated
restarts, `strict`-refusal of forged `scheduled_sends` mid-restore as a
40-trial property, and `plugins=` exactly-once hook delivery — all confirm
the changelog's #226/#227/#230 descriptions with no contradicting edge
case found.

**No new `D13-determinism-n` defects are raised this pass.**

The task-identity matrix, `RuntimeWarning` surfacing probe, soak, livelock
fuzz, forgery, and BENCH-6 items in §3 are explicitly not covered and
should not be read as passing.
